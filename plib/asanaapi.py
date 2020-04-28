import asana
import time
import datetime as dt

class Status:
    """wrapper for asana api"""
    def __init__(self, **kwargs):
        """ asana wrangling

        Anatomy of an Asana task:

        {
         'assignee_status': 'upcoming',
         'projects': [{'gid': '1143023741172261', 'resource_type': 'project'}],
         'completed': False,
         'name': 'foo bar baz',
         'assignee': None,
         'gid': '1168061995539043',
         'completed_at': None,
         'modified_at': '2020-03-24T15:11:50.284Z',
         'created_at': '2020-03-24T15:11:50.284Z',
        }

        """
        self.args = kwargs
        self.members = []
        self.task_history = {}
        self.logger = None
        self.space = None
        self.projects = []
        self.space_users = []
        # project gid/task gid
        self.task_fmt = 'https://app.asana.com/0/{}/{}'
        self.project_fmt = 'https://app.asana.com/0/{}/'

        if kwargs['token']:
            self.con = asana.Client.access_token(kwargs['token'])
        else:
            self.con = None

        # To get content add: "this.notes"
        self.task_fields = [
            "this.name",
            "this.projects",
            "this.created_at",
            "this.completed",
            "this.modified_at",
            "this.assignee",
            "this.assignee_status",
            "this.completed_at",
            "this.name",
        ]

    def progress_column(self, project, tasks):
        progress = []
        for task in tasks:
            if task['assignee'] and not task['completed']:
                self.logging('marked as progress: {}\n'.format(task))
                progress.append(task)
        return progress

    def backlog_column(self, project, tasks):
        backlog = []
        for task in tasks:
            if not task['assignee'] and not task['completed']:
                self.logging('marked as backlog: {}\n'.format(task))
                backlog.append(task)
        return backlog

    def logging(self, msg):
        if self.logger:
            self.logger.debug(msg)
            return
        print(msg)

    def generate_project_link(self, project):
        pgid = self.projects[project]['gid']
        return self.project_fmt.format(pgid)

    def generate_task_link(self, task):
        try:
            return self.task_fmt.format(task['projects'][0]['gid'], task['gid']), task['name']
        except:
            self.logging('failed to generate link for {}'.format(task))
            raise

    def get_workspace(self):
        """ Asana is broken up into 'workspaces'
        which have 'projects' which have tasks.
        We need to get the workspace info from
        the name validate.
        :action: sets self.space with dict
        """
        if self.space:
            return self.space

        workspaces = self.con.workspaces.find_all()

        space = None
        for i, val in enumerate(workspaces):
            if val['name'] == self.args['workspace']:
                self.space = val
                return self.space
        else:
            raise Exception('Not a valid Asana Workspace')

    def get_project_info(self):
        # TODO: integrate this with a parent class stub for phab
        workspace = self.get_workspace()
        projects = self.con.projects.find_all({'workspace': workspace['gid']})

        proj_info = {}
        for i, val in enumerate(projects):
            if val['name'] in self.args['projects']:
                self.logging('Matching "{}" project from asana api'.format(val['name']))
                proj_info[val['name']] = val

        self.logging('Count of known projects: {}'.format(len(proj_info)))
        if not proj_info:
            raise Exception('Invalid projects provided')

        self.logging('Setting project_info: {}'.format(proj_info))
        self.projects = proj_info

    def date_to_epoch(self, date_str):
        # 2020-04-01T21:23:54.346Z
        mdate = dt.datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S.%fZ')
        return mdate.timestamp()

    def get_member_info(self, realname, username, agents=False):
        if not self.space_users:
            space_users = self.con.users.get_users_for_workspace(self.space['gid'])
            self.space_users = list(space_users)

        gid = [u['gid'] for u in self.space_users if u['name'] == username][0]
        details = self.get_user_info(gid)
        return details

    def get_user_info(self, id):
        return self.con.users.find_by_id(id)

    def get_user_assigned_tasks(self, gid):

        # TODO: gotta be a saner way to query for open and assigned
        # assigned_generator = self.con.tasks.find_all({'assignee': gid,
        #                                                'workspace': self.space['gid'],
        #                                                "opt_fields":self.task_fields})
        # return [t for t in list(assigned_generator) if not t['completed']]

         assigned = []
         for project, details in self.task_history.items():
             for task in details['tasks_dedup']:
                 if task['assignee'] and task['assignee']['gid'] == gid:
                     if not task['completed']:
                         assigned.append(task)
         return assigned

    def user_assigned(self, user_details, best_by_date):
        assigned = self.get_user_assigned_tasks(user_details['gid'])
        moldy_threshold = int(time.time()) - best_by_date
        moldy = self.task_mod_before_date(assigned, moldy_threshold)
        return assigned, moldy

    def task_mod_before_date(self, tasks, mtime):
        modded = []
        for task in tasks:
            if self.date_to_epoch(task['modified_at']) < mtime:
                modded.append(task)
        modded_sorted = sorted(modded, key = lambda i: i['modified_at'])
        return modded_sorted

    def task_mod_after_date(self, tasks, mtime):
        modded = []
        for task in tasks:
            if self.date_to_epoch(task['modified_at']) > mtime:
                modded.append(task)
        modded_sorted = sorted(modded, key = lambda i: i['modified_at'])
        return modded_sorted

    def task_created_after_date(self, tasks, ctime):
        created_after = []
        for task in tasks:
            if self.date_to_epoch(task['created_at']) > ctime:
                created_after.append(task)
        created_sorted = sorted(created_after, key = lambda i: i['created_at'])
        return created_sorted

    def get_project_tasks(self, gid):
        return self.con.tasks.find_all({'project': gid,
                                         "opt_fields":self.task_fields})

    def get_tasks_created_since(self, project, days):
        """ get tasks from last n days with summary stats
        :param project: str
        :param days: int
        :return: task list
        """
        start_time = int(time.time()) - (days * 86400)
        self.logging('"{}": days {} start time {}'.format(project, days, start_time))

        if not self.projects:
            self.get_project_info()

        if project in self.task_history and start_time > self.task_history[project]['start_time']:
            cached_tasks = self.task_history[project]['tasks']
            self.logging('{} cached for {} days ({})'.format(project, days, len(cached_tasks)))
            created_after = self.task_created_after_date(cached_tasks, start_time)
            self.logging('{} cached for {} days ({})'.format(project, days, len(created_after)))
            return created_after

        pgid = self.projects[project]['gid']
        self.logging('{}: querying API for tasks'.format(self.projects[project]['name']))
        tasks_raw = self.get_project_tasks(pgid)

        task_dedup = []
        for t in tasks_raw:
            if any([*map(lambda i: i in t['name'], self.args['ignore'])]):
                self.logging('Ingnoring as dupe: {}'.format(t['name']))
            else:
                task_dedup.append(t)

        self.logging('Dedupe task count from "{}": {}'.format(project, len(task_dedup)))

        tasks_from_date = self.task_created_after_date(task_dedup, start_time)

        self.task_history[project] = {}
        self.task_history[project]['start_time'] = start_time
        self.task_history[project]['tasks'] = tasks_from_date
        self.task_history[project]['tasks_dedup'] = task_dedup
        return tasks_from_date

    def tasks_summary(self, tasks, enabled_fields):
        """ returns a dict of summary info about a list of tasks
        :param tasks: list
        :return: list of summary dicts by summary_field
        """
        summary = {}
        summary_fields = {'status':
                              'completed',
                         }

        # return count(s) of unique summary_field items for all tasks
        for field, key in summary_fields.items():
            if field not in enabled_fields:
                continue

            summary[field] = {}
            for task in tasks:
                extracted = task.get(key, None)
                if extracted is not None:
                    if extracted not in summary[field]:
                        summary[field][extracted] = 0
                    summary[field][extracted] += 1

        # As status is a bool set to human readable
        # If more fields need this treatment down the road
        # rethink the definition datastructure to include this logic
        status = {}
        status_bool = summary['status']
        for k, v in status_bool.items():
            if k:
                status['resolved'] = v

            else:
                status['open'] = v

        summary['status'] = status
        return summary

    def column_tasks(self, column, project):
        """ Get tasks by workboard column
        :param: str
        :return: list
        """

        columns = {
            'progress': self.progress_column,
            'backlog': self.backlog_column
        }

        if column not in columns.keys():
            raise Exception('Invalid column {}'.format(id))

        if project not in self.task_history.keys():
            self.logging('{} not populated for column extraction')
            return []

        function = columns[column]
        tasks = function(project, self.task_history[project]['tasks_dedup'])
        return tasks
