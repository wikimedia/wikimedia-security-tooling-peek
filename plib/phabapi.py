import time
from phabricator import Phabricator
from plib import util
from collections import Counter


class Status:
    """wrapper for phab api"""
    def __init__(self, **kwargs):

        self.args = kwargs
        self.members = []
        self.project_details = {}
        self.task_history = {}
        self.logger = None

        self.task_fmt = "https://phabricator.wikimedia.org/T{}"
        self.project_fmt = "https://phabricator.wikimedia.org/tag/{}"

        if kwargs['host']:
            self.con = Phabricator(token=kwargs['token'],
                                    host=kwargs['host'],
                                    timeout=kwargs['timeout'])
        else:
            self.con = None

    def logging(self, msg):
        if self.logger:
            self.logger.debug(msg)
            return
        print(msg)

    def me(self):
        return self.con.user.whoami()

    def generate_project_link(self, project):
        return self.project_fmt.format(project)

    def generate_task_link(self, task):
        return self.task_fmt.format(task['id']), task['fields']['name']

    def page_query(self,
                    function,
                    queryKey='open',
                    order=None,
                    limit=100,
                    constraints={},
                    query_delay=.5):
        """ Query paged results until
        :param queryKey: string for main query modifyer
        :param order: string or None for result ordering
        :param limit: per query result limit #note this seems broken after 2
        :param constraints: dict of query modifiers
        """
        total_results = []
        result = function(queryKey=queryKey, order=order, limit=limit,
                          constraints=constraints)
        while 1:
            total_results += result['data']
            after = result['cursor']['after']
            result = function(queryKey=queryKey, order=order, limit=limit, after=after,
                              constraints=constraints)
            if result['cursor']['after'] is None:
                break
            time.sleep(query_delay)
        return total_results

    def get_member_info(self, realname, username, agents=False):
        details = self.con.user.query(usernames=[username])[0]
        if not agents and 'agent' in details['roles']:
            print('Ignore agent {}'.format(details))
            return {}
        return details

    def user_info(self, phid):
        return self.con.user.query(phids=[phid])[0]

    def user_assigned(self, user_details):
        assigned = self.con.maniphest.search(queryKey='open',
                                             attachments={
                                                 "projects": True
                                             },
                                         constraints={'assigned': [user_details['phid']]})
        return assigned['data']

    def task_mod_after_date(self, tasks, age):
        modded = []
        for task in tasks:
            if task['fields']['dateModified'] < time.time() - age:
                modded.append(task)
        modded_sorted = sorted(modded, key = lambda i: i['fields']['dateModified'])
        return modded_sorted

    def task_created_after_date(self, tasks, age):
        created_after = []
        for task in tasks:
            if task['fields']['dateCreated'] > age:
                created_after.append(task)
        created_after_sorted = sorted(created_after, key = lambda i: i['fields']['dateCreated'])
        return created_after_sorted

    def get_tasks_created_since(self, project, days):
        """ get tasks from last n days with summary stats
        :param project: str
        :param days: int
        :return: task list
        """
        start_date = int(time.time()) - (days * 86400)
        if project in self.task_history and start_date > self.task_history[project]['start_date']:
            self.logging('return cached for {} {}'.format(project, days))
            cached_tasks = self.task_history[project]['tasks']
            return self.task_created_after_date(cached_tasks, start_date)

        tasks = self.page_query(function=self.con.maniphest.search,
                   queryKey='all',
                   order='closed',
                   constraints={'projects': [project],
                                'createdStart': start_date },
                   query_delay=1)

        if project not in self.task_history:
            self.task_history[project] = {}
        self.task_history[project]['start_date'] = start_date
        self.task_history[project]['tasks'] = tasks
        return tasks

    def tasks_summary(self, tasks, enabled_fields):
        """ returns a dict of summary info about a list of tasks
        :param tasks: list
        :return: list of summary dicts by summary_field
        """
        summary = {}
        summary_fields = {'priority':
                              ('fields', 'priority', 'name'),
                          'status':
                              ('fields', 'status', 'value'),
                          'issue type':
                              ('fields', 'subtype'),
                         }

        # return count(s) of unique summary_field items for all tasks
        for field, key in summary_fields.items():

             if not field in enabled_fields:
                 continue

             extracted_fields = []
             for task in tasks:
                 extracted_fields.append(util.safeget(task, key))
             if any(extracted_fields):
                 summary[field] = dict(Counter(extracted_fields))
             else:
                 summary[field] = {}
        return summary

    def column_tasks(self, column, project):
        """ Get tasks by workboard column
        :param column: id str
        :param project: str
        :return: list
        """
        return self.page_query(function=self.con.maniphest.search,
                                                   constraints={
                                                    'columnPHIDs': [
                                                     column,
                                                    ],
                                                   },
                                                  )
    def anti_punassigned(self, antinfo, pinfo):
        """ return a list of tasks that are in progress but unassigned
        :param tasks_dict: list of standard phab task dicts
        """
        tasks_dict = pinfo['columns']['progress']

        punassigned = []
        for task in tasks_dict:
            if task['fields']['ownerPHID'] is None:
                punassigned.append(task)
        return punassigned

    def anti_watching_dormant(self, antinfo, pinfo):
        tasks_dict = pinfo['columns']['watching']
        best_by_date = antinfo['age']
        return self.task_mod_after_date(tasks_dict, best_by_date)

    def anti_moldy(self, tasks, antinfo, beinfo):
        best_by_date = antinfo['age']
        return self.task_mod_after_date(tasks, best_by_date)

    def anti_assigned_wo_reporting_project(self, tasks, antinfo, beinfo):
        if not self.project_details:
            self.project_details = self.con.project.query(names=list(beinfo['projects'].keys()))
        reported_phids = set(self.project_details['data'].keys())

        out = []
        for task in tasks:
            task_projects = task['attachments']['projects']['projectPHIDs']
            matched = set(task_projects).intersection(reported_phids)
            if not matched:
                out.append(task)
        return out
