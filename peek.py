#!/usr/bin/python3
import copy
import datetime
import logging
import optparse
import os
import sys
import time
import yaml
from collections import Counter
from jinja2 import Environment
from jinja2 import FileSystemLoader
from pathlib import Path
from plib import util
from plib import phabapi
from plib import asanaapi
from plib import format


def getname():
    """ get stem name of this script"""
    return Path(__file__).stem


def anti_punassigned(tasks_dict):
    """ return a list of tasks that are in progress but unassigned
    :param tasks_dict: list of standard phab task dicts
    """
    punassigned = []
    for task in tasks_dict:
        if task['fields']['ownerPHID'] is None:
            punassigned.append(task)
    return punassigned

def get_wclass(backend):
    backend_classes = {
        'asana': asanaapi,
        'phab': phabapi,
    }
    return backend_classes[backend]

def get_wobj(backend, config):
    wclass = get_wclass(backend)
    try:
        wobj = wclass.Status(**config['backends'][backend])
        return wobj
    except Exception as e:
        logging.critical('Failed to connect: {}'.format(e))
        sys.exit(1)

def main():

    parser = optparse.OptionParser()
    parser.add_option('-c', '--config', default='config.yml', dest="config", type="str")
    parser.add_option('-j', '--job', default='', dest="job", type="str")
    parser.add_option('-p', action='store_true', default=False, dest='echo')
    parser.add_option('-s', action='store_true', default=False, dest='send')
    parser.add_option('-v', action='store_true', default=False, dest='verbose')

    options, remainder = parser.parse_args()


    logging.basicConfig(
        level=logging.DEBUG if options.verbose else logging.INFO,
        format="%(asctime)s:%(levelname)s:%(message)s"
        )
    logging.debug(options)

    def loadconfig(configs):
        out = {}
        for c in configs.split(','):
            if not c:
                continue
            try:
                with open(c, 'r') as ymlfile:
                    v = yaml.load(ymlfile)
                    logging.debug(v)
                    out.update(v)
            except Exception as e:
                logging.critical('failed to read config file {}'.format(c))
        return out

    cfg = loadconfig(options.config)
    if not cfg:
        sys.exit(1)
        raise Exception('Failure to gather configuration from {}'.format(options.config))

    if options.job:
        logging.debug("Overriding job name to: {}".format(options.job))
        cfg['job'] = options.job

    meta = {}
    meta['starttime'] = time.time()
    meta['moldy'] = {}
    meta['enabled_projects'] = []
    meta['enabled_backends'] = []
    meta['moldy']['epoch_time'] = cfg['users']['moldy'] * 86400

    total = {}
    total['max'] = max(cfg['history'])
    total['columns'] = {}
    total['projects'] = {}
    total['projects']['history'] = {}
    total['users'] = {}
    total['users']['group'] = {}
    total['users']['group']['assigned'] = []
    total['users']['group']['moldy'] = []
    total['users']['individual'] = {}
    total['summary_header'] = {}

    total['anti'] = {}

    bes = {}
    for be, beinfo in sorted(cfg['backends'].items(), reverse=True):
        bes[be] = {}
        logging.info('Processing backend: {}'.format(be))

        if not beinfo.get('enabled', False):
            logging.warning('skipping {} as not enabled'.format(be))
            continue

        meta['enabled_backends'].append(be)

        wobj = get_wobj(be, cfg)
        wobj.logger = logging

        # Projects
        projects = {}
        for project in sorted(beinfo['projects'].keys()):
            logging.info('Processing {} project {}'.format(be, project))
            meta['enabled_projects'].append(project)

            projects[project] = {}
            projects[project]['history'] = {}
            projects[project]['show'] = {}

            for duration in sorted(cfg['history'], reverse=True):

                tasks = wobj.get_tasks_created_since(project, duration)
                logging.debug("{}: {} duration at task count {}".format(project, duration, len(tasks)))

                summary_fields = cfg['backends'][be].get('summary_fields', cfg['summary_fields'])

                stats = wobj.tasks_summary(tasks, summary_fields)

                projects[project]['history'][duration] = {}
                projects[project]['history'][duration]['tasks'] = tasks
                projects[project]['history'][duration]['stats'] = stats

                if not duration in total['projects']['history']:
                    total['projects']['history'][duration] = {}
                    total['projects']['history'][duration]['stats'] = copy.deepcopy(stats)

                for field, values in stats.items():
                    thisproj = stats[field]
                    sofar = total['projects']['history'][duration]['stats'][field]
                    new = Counter(thisproj) + Counter(sofar)
                    total['projects']['history'][duration]['stats'][field] = dict(new)

        summary_header = {}
        for project, pinfo in projects.items():
            headers = format.tasks_summary_header(pinfo['history'])
            for k, v in headers.items():
                if k not in summary_header:
                    summary_header[k] = v
                else:
                    summary_header[k] = list(set(summary_header[k] + v))

                if k not in total['summary_header']:
                    total['summary_header'][k] = v
                else:
                    total['summary_header'][k] = list(set(total['summary_header'][k] + v))

        for project, pinfo in projects.items():
            projects[project]['show']['uri'] = wobj.generate_project_link(project)
            projects[project]['history']['summary_table'] = format.tasks_summary_table(summary_header, pinfo['history'])

        # Columns
        for project, pinfo in beinfo['projects'].items():
            projects[project]['columns'] = {}
            for column, id in beinfo['projects'][project]['columns'].items():
                ctasks = wobj.column_tasks(id, project)
                logging.debug('Get {} id {} for {}: {}'.format(column, id, project, len(ctasks)))

                if column not in projects[project]['columns']:
                    projects[project]['columns'][column] = ctasks
                else:
                    projects[project]['columns'][column] += util.dedupe_list_of_dicts(ctasks)

                if column not in total['columns']:
                    total['columns'][column] = ctasks
                else:
                    total['columns'][column] += util.dedupe_list_of_dicts(ctasks)

        # Anti
        if be == 'phab':
            # This works here as it's only a valid state for one backend
            total['anti']['total'] = 0
            total['anti']['patterns'] = {}

            # This needs cleanup and abstraction and such desparately.
            total['anti']['patterns']['Progress But Unassigned'] = []
            for project, pinfo in projects.items():
                punassigned = anti_punassigned(pinfo['columns']['progress'])
                if punassigned:
                    logging.info("{} anti found count {}".format(project, len(punassigned)))
                    total['anti']['patterns']['Progress But Unassigned'] += punassigned
                    total['anti']['patterns']['Progress But Unassigned'] = util.dedupe_list_of_dicts(total['anti']['patterns']['Progress But Unassigned'])

            # Create total out of deduped list counts
            for pattern, matches in total['anti']['patterns'].items():
                total['anti']['total'] += len(matches)

        bes[be]['projects'] = projects
        # Users
        report_users = cfg['users']['map']
        users = {}

        if 'count' not in total['users']:
            total['users']['group']['count'] = len(report_users)

        for u, be_matches in report_users.items():
            users[u] = {}
            users[u] = {}
            users[u]['details'] = wobj.get_member_info(u, be_matches[be])

        logging.debug('{} member details'.format(be, users))

        for u, uinfo in users.items():

            for sa, sa_info in cfg['users']['attributes']['show'].items():
                sa_backend = sa_info['backend']
                sa_key = sa_info['key']
                if be == sa_backend:
                    uinfo[sa_key] = uinfo['details'][sa]

            assigned, moldy = wobj.user_assigned(uinfo['details'], meta['moldy']['epoch_time'])
            logging.info('{} {} assigned {} moldy {}'.format(u, be, len(assigned), len(moldy)))

            users[u]['moldy'] = {}

            if u not in total['users']['individual']:
                total['users']['individual'][u] = {}
            if 'moldy' not in total['users']['individual'][u]:
                total['users']['individual'][u]['moldy'] = []

            users[u]['moldy']['all'] = moldy

            total['users']['group']['moldy'] += util.dedupe_list_of_dicts(moldy)
            total['users']['individual'][u]['moldy'] += util.dedupe_list_of_dicts(moldy)

            users[u]['moldy']['shown'] = []
            m_shown = users[u]['moldy']['all'][:cfg['users']['show_moldy']]
            for task in m_shown:
                users[u]['moldy']['shown'].append(wobj.generate_task_link(task))

            if 'assigned' not in users[u]:
                users[u]['assigned'] = assigned
            else:
                users[u]['assigned'] += util.dedupe_list_of_dicts(assigned)

            total['users']['group']['assigned'] += util.dedupe_list_of_dicts(assigned)

            if 'assigned' not in total['users']['individual'][u]:
                total['users']['individual'][u]['assigned'] = []
            total['users']['individual'][u]['assigned'] += util.dedupe_list_of_dicts(assigned)

            time.sleep(beinfo.get('query_delay', .5))

        bes[be]['users'] = users

    total['projects']['history']['summary_table'] = format.tasks_summary_table(total['summary_header'], total['projects']['history'])

    env = Environment(
        loader=FileSystemLoader(cfg['templates']))
    template = env.get_template('body.html')

    meta['runtime'] = int(time.time() - meta['starttime'])
    meta['name'] = getname()

    data=[meta, bes, cfg, total]
    template.globals['now'] = int(time.time())
    output = template.render(data=data)

    if options.echo:
        print(output)

    if options.send:
        now = datetime.datetime.now()
        subject = "{} {}".format(cfg['job'], now.strftime('%Y-%m-%d'))
        logging.info("{} sending email '{}'".format(meta['name'], subject))
        util.send_email(cfg['email']['from'],
                         cfg['email']['to'],
                         subject,
                         output,
                         cfg['email']['server'])
main()
