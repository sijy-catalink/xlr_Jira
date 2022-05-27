import com.xhaus.jyson.JysonCodec as Json
import string
import sys
from base64 import b64encode
from java.time import Instant
from java.util import Date

from util import error
from xlrelease.HttpRequest import HttpRequest
from java.time.format import DateTimeFormatter

# Constants
MAX_RESULTS = 1000

class CatalinkJiraServer:

    def __init__(self, jira_server, username, password, api_token, encoding = 'utf-8', task_reporting_api = None, task = None):
        if jira_server is None:
            error('No server provided.')

        self.jira_server = jira_server
        self.username = username
        self.password = password
        self.api_token = api_token
        self.encoding = encoding
        self.task_reporting_api = task_reporting_api
        self.task = task
        self.hosting_option = self._getHostingOption()

    def queryIssues(self, query, options = None):
        if not query:
            error('No JQL query provided.')

        if self._getHostingOption() == 'SERVER':
            maxResults = 1000
        else:
            maxResults = 100
        # offset determines which issue to startAt
        offset = 0
        issues = {}

        # Parse result
        while offset < MAX_RESULTS:
            # Create POST body
            content = {
                'jql': query,
                'startAt': offset,
                'fields': ['summary', 'status', 'assignee'],
                'maxResults': maxResults
            }

            # Do request
            request = self._createRequest()
            response = request.post(self._getVersionUri() + '/search', self._serialize(content),
                                    contentType='application/json', headers=self._createApiTokenHeader())

            if response.status == 200:
                data = Json.loads(response.response)
                if not data['issues']:
                    break
                offset = offset + maxResults
                for item in data['issues']:
                    issue = item['key']
                    assignee = "Unassigned" if (item['fields']['assignee'] is None) else item['fields']['assignee']['displayName']
                    issues[issue] = {
                        'issue'   : issue,
                        'summary' : item['fields']['summary'],
                        'status'  : item['fields']['status']['name'],
                        'assignee': assignee,
                        'link'    : "{1}/browse/{0}".format(issue, self.jira_server['url'])
                    }
            else:
                error(u"Failed to execute search '{0}' in JIRA.".format(query), response)

        return issues

    def query(self, query, quiet = False):
        if not query:
            error('No JQL query provided.')

        # Create POST body
        content = {
            'jql': query,
            'startAt': 0,
            'fields': ['summary', 'issuetype', 'updated', 'status', 'reporter'],
            'expand': ['changelog'],
            'maxResults': 1000
        }

        # Do request
        request = self._createRequest()
        response = request.post(self._getVersionUri() + '/search', self._serialize(content),
                                contentType='application/json', headers=self._createApiTokenHeader())
        # Parse result
        if response.status == 200:
            data = Json.loads(response.response)

            if not quiet:
                print "#### Issues found"
            issues = {}
            for item in data['issues']:
                issue = item['key']
                issues[issue] = item['fields']['summary']
                if not quiet:
                    print u"* {0} - {1}".format(self.link(issue), item['fields']['summary'])

                try:
                    if self.task_reporting_api and self.task:
                        planRecord = self.task_reporting_api.newPlanRecord()
                        planRecord.targetId = self.task.id
                        planRecord.ticket = issue
                        planRecord.title = item['fields']['summary']
                        planRecord.ticketType = (item['fields'].get('issuetype', {})).get('name')
                        updated = item['fields'].get('updated')
                        if updated:
                            planRecord.updatedDate = Date.from(Instant.from(DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSSX").parse(updated)))

                        histories = item.get('changelog', {}).get('histories', [])
                        if len(histories) > 0:
                            updatedBy = next(iter(histories), {}).get('author', {}).get('displayName')
                        else:
                            updatedBy = item['fields'].get('reporter', {}).get('displayName')

                        if updatedBy:
                            planRecord.updatedBy = updatedBy

                        status = item['fields'].get('status', {}).get('name')
                        if status:
                            planRecord.status = status
                        planRecord.ticket_url = self.jira_server['url'].rstrip('/') + '/browse/' + issue
                        planRecord.serverUrl = self.jira_server['url']
                        if not self.username:
                            planRecord.serverUser = self.jira_server['username']
                        else:
                            planRecord.serverUser = self.username

                        self.task_reporting_api.addRecord(planRecord, True)
                except:
                    print "\n\n"
                    print sys.exc_info()
            if not quiet:
                print "\n"
            return issues

        else:
            error(u"Failed to execute search '{0}' in JIRA.".format(query), response)

    def createIssue(self, project, title, description, issue_type):
        # Create POST body
        content = {
            'fields': {
                'project': {
                    'key': project
                },
                'summary': title,
                'description': description,
                'issuetype': {
                    'name': issue_type
                }
            }
        }

        # Do request
        request = self._createRequest()
        response = request.post(self._getVersionUri() + '/issue', self._serialize(content),
                                contentType='application/json', headers=self._createApiTokenHeader())

        # Parse result
        if response.status == 201:
            data = Json.loads(response.response)
            issue_id = data.get('key')
            print u"Created {0} in JIRA.".format(self.link(issue_id))
            if self.task_reporting_api and self.task:
                try:
                    self.query("key=" + issue_id, quiet = True)
                except:
                    print "\n\n"
                    print sys.exc_info()
            return issue_id
        else:
            error("Failed to create issue in JIRA.", response)

    def createIssueJson(self, json_obj):
        # Do request
        request = self._createRequest()
        response = request.post(self._getVersionUri() + '/issue', json_obj, contentType='application/json',
                                headers=self._createApiTokenHeader())

        # Parse result
        if response.status == 201:
            data = Json.loads(response.response)
            issue_id = data.get('key')
            print u"Created {0} in JIRA.".format(self.link(issue_id))
            return issue_id
        else:
            error("Failed to create issue in JIRA.", response)

    def createSubtask(self, project, title, description, parent_issue_key, issueTypeName):
        # Send an API request to find the issuetype id to create a Sub-task
        issueTypeUri = self._getVersionUri() + "/issue/createmeta?projectKeys=%s&expand=projects.issuetypes.fields" % project
        issueTypeRequest = self._createRequest()
        issueTypeResponse = issueTypeRequest.get(issueTypeUri, contentType="application/json",
                                                 headers=self._createApiTokenHeader())
        if issueTypeResponse.status == 200:
            data = Json.loads(issueTypeResponse.response)
            for issueType in data['projects'][0]['issuetypes']:
                if issueType['subtask']:
                    if not issueTypeName or issueType['name'] == issueTypeName:
                        type_id = issueType['id']
                        break
            else:
                error("Failed to find issue type '%s' for '%s' project." % (issueTypeName, project))
        else:
            error("Failed to get issue types for '%s' project." % project, issueTypeResponse)
        # Create POST body
        content = {
            'fields': {
                'project': {
                    'key': project
                },
                'parent': {
                    'key': parent_issue_key
                },
                'summary': title,
                'description': description,
                'issuetype': {
                    'id': type_id
                }
            }
        }
        # Do request
        request = self._createRequest()
        response = request.post(self._getVersionUri() + '/issue', self._serialize(content),
                                contentType='application/json', headers=self._createApiTokenHeader())

        # Parse result
        if response.status == 201:
            data = Json.loads(response.response)
            subtask_id = data.get('key')
            print u"Created {0} in JIRA.".format(self.link(subtask_id))
            return subtask_id
        else:
            error("Failed to create subtask in JIRA.", response)

    def updateIssue(self, issue_id, new_status, comment, new_summary = None, add_record = True):
        # Check for ticket
        self._checkIssue(issue_id)

        # Status transition
        if new_status:
            self._transitionIssue(issue_id, new_status, new_summary)
            if comment:
                self._updateComment(issue_id, comment)
        else:
            self._updateIssue(issue_id, new_summary, comment)

        print u"Updated {0}".format(self.link(issue_id))
        if add_record and self.task_reporting_api and self.task:
            try:
                self.query("key=" + issue_id, quiet = True)
            except:
                print "\n\n"
                print sys.exc_info()
        print
    
    def updateField(self, issue_id, field_name, new_value, comment):
        # Check for ticket
        self._checkIssue(issue_id)
        
        # Build the data package
        updated_data = self._getUpdatedIssueFieldData(field_name, new_value, comment)
       
        # Update Issue
        self._updateIssueField(issue_id, updated_data)

        print u"Updated Issue: {0} , Field: {1}, Value: {2}".format(self.link(issue_id),field_name, new_value)
        print
    
    def _getUpdatedIssueFieldData(self, fieldname, fieldvalue , comment):
        updated_data = {}


        if fieldname:
            updated_data.update({
                "{0}".format(fieldname): [
                    {
                        "add": 
                            {
                                "name": "{0}".format(fieldvalue)
                            }    
                    }
                ]
            })

        if comment:
            updated_data.update({
                "comment": [
                    {
                        "add": {
                            "body": comment
                        }
                    }
                ]
            })

        return updated_data
        
    def assignIssue(self, issue_id, accountId, comment):
        # Check for ticket
        self._checkIssue(issue_id)

        # Status transition
        self._assignIssue(issue_id, accountId)
        
        if comment:
                self._updateComment(issue_id, comment)
        else:
                self._updateComment(issue_id, "Issue assigned by XLRelease to AccountID: " + accountId)

        print u"Assigned {0} to {1}".format(self.link(issue_id), accountId)
        
        

    def checkQuery(self, query):
        if not query:
            error('No JQL query provided.')

        # Create POST body
        content = {
            'jql': query,
            'startAt': 0,
            'fields': ['summary', 'status']
        }

        # Do request
        request = self._createRequest()
        response = request.post(self._getVersionUri() + '/search', self._serialize(content),
                                contentType='application/json', headers=self._createApiTokenHeader())
        if response.status != 200:
            error(u"Failed to execute search '{0}' in JIRA.".format(query), response)
        data = Json.loads(response.response)
        counter = 0
        issues = {}
        while response.status == 200 and 100*counter < data["total"]:
            data = Json.loads(response.response)
            for item in data['issues']:
                issue = item['key']
                issues[issue] = (item['fields']['summary'], item['fields']['status']['name'])
            counter += 1
            content['startAt'] = 100*counter
            response = request.post(self._getVersionUri() + '/search', self._serialize(content),
                                    contentType='application/json', headers=self._createApiTokenHeader())
            if response.status != 200:
                error(u"Failed to execute search '{0}' in JIRA.".format(query), response)
        return issues


    def getVersionIdsForProject(self, projectId):
        if not projectId:
            error("No project id provided.")
        request = self._createRequest()
        response = request.get(self._versionsUrl(projectId), contentType="application/json",
                                headers=self._createApiTokenHeader())
        if response.status != 200:
            error(u"Unable to find versions for project id %s" % projectId, response)
        versionIds = []
        for item in Json.loads(response.response):
            versionIds.append(item['id'])
        if not versionIds:
            print "No versions found for project id %s" % projectId
        else:
            print str(versionIds) + "\n"
        return versionIds

    def queryForFields(self, query, fields):
        if not query:
            error('No JQL query provided.')

        # Create POST body
        content = {
            'jql': query,
            'startAt': 0,
            'fields': fields,
            'maxResults': 1000
        }

        # Do request
        request = self._createRequest()
        response = request.post(self._getVersionUri() + '/search', self._serialize(content),
                                contentType='application/json', headers=self._createApiTokenHeader())

        # Parse result
        if response.status == 200:
            data = Json.loads(response.response)

            issues = []
            for item in data['issues']:
                issue = {}
                for field in fields:
                    issue[field] = item[field]
                issues.append(issue)
            return issues
        else:
            error(u"Failed to execute search '{0}' in JIRA.".format(query), response)

    def queryForIssueIds(self, query):
        issues = self.queryForFields(query, ["id"])
        # for backwards compatibility, return a flat list with ids
        return [x["id"] for x in issues]

    def get_boards(self, board_name):
        if not board_name:
            error("No board name provided.")
        request = self._createRequest()
        response = request.get("/rest/agile/1.0/board?name=%s" % board_name, contentType="application/json",
                               headers=self._createApiTokenHeader())
        if response.status != 200:
            error(u"Unable to find boards for {0}".format(board_name), response)
        return Json.loads(response.response)['values']

    def get_all_sprints(self, board):
        if not board:
            error("No board id provided")
        request = self._createRequest()
        response = request.get("/rest/agile/1.0/board/%s/sprint" % board["id"], contentType="application/json",
                               headers=self._createApiTokenHeader())
        sprints = {}
        if response.status != 200:
            error(u"Unable to find sprints for board {0}".format(board["name"]), response)
        sprints_json = Json.loads(response.response)['values']
        for sprint_json in sprints_json:
            sprints[sprint_json["name"]] = sprint_json["id"]
            print "| %s | %s | %s | %s |" % (sprint_json["name"], sprint_json["id"],
                                             sprint_json["startDate"] if sprint_json.has_key(
                                                 "startDate") else "not defined",
                                             sprint_json["endDate"] if sprint_json.has_key(
                                                 "endDate") else "not defined")
        return sprints

    ######

    def _getUpdatedIssueData(self, summary, comment):
        updated_data = {}

        if comment:
            updated_data.update({
                "comment": [
                    {
                        "add": {
                            "body": comment
                        }
                    }
                ]
            })

        if summary is not None:
            updated_data.update({
                "summary": [
                    {
                        "set": summary
                    }
                ]
            })

        return updated_data

    def _updateComment(self, issue_id, comment):
        request = self._createRequest()
        response = request.post(self._issueUrl(issue_id) + "/comment", self._serialize({"body": comment}),
                                contentType='application/json', headers=self._createApiTokenHeader())

        if response.status != 201:
            error(u"Unable to comment issue {0}. Make sure you have 'Add Comments' permission.".format(self.link(issue_id)), response)


    def _updateIssueField(self, issue_id, updated_data):

        # Create POST body
        request_data = {"update": updated_data}

        # Do request
        request = self._createRequest()
        response = request.put(self._issueUrl(issue_id), self._serialize(request_data), contentType='application/json', headers=self._createApiTokenHeader())

        # Parse result
        if response.status != 204:
            error(u"Unable to update issue {0}. Please make sure the issue is not in a 'closed' state.".format(self.link(issue_id)), response)
            


    def _updateIssue(self, issue_id, new_summary, comment):

        updated_data = self._getUpdatedIssueData(new_summary, comment)

        # Create POST body
        request_data = {"update": updated_data}

        # Do request
        request = self._createRequest()
        response = request.put(self._issueUrl(issue_id), self._serialize(request_data),
                               contentType='application/json', headers=self._createApiTokenHeader())

        # Parse result
        if response.status != 204:
            error(u"Unable to update issue {0}. Please make sure the issue is not in a 'closed' state. Response details {1}".format(self.link(issue_id),response), response)

    def _assignIssue(self, issue_id, accountId):
        updated_data = {}
        updated_data.update({
                "accountId": accountId
            })

        # Create POST body
        request_data = updated_data

        # Do request
        request = self._createRequest()
        response = request.put(self._issueAssignUrl(issue_id), self._serialize(request_data),
                               contentType='application/json', headers=self._createApiTokenHeader())

        # Parse result
        if response.status != 204:
            error(u"Unable to assign issue {0}. Please make sure the issue is not in a 'closed' state.".format(self.link(issue_id)), response)

    def _transitionIssue(self, issue_id, new_status, summary):

        issue_url = self._issueUrl(issue_id)

        # Find possible transitions
        request = self._createRequest()
        response = request.get(issue_url + "/transitions?expand=transitions.fields",
                               contentType='application/json', headers=self._createApiTokenHeader())

        if response.status != 200:
            error(u"Unable to find transitions for issue {0}".format(self.link(issue_id)), response)

        transitions = Json.loads(response.response)['transitions']

        # Check  transition
        wanted_transaction = -1
        for transition in transitions:
            if transition['to']['name'].lower() == new_status.lower():
                wanted_transaction = transition['id']
                break

        if wanted_transaction == -1:
            error(u"Unable to find status {0} for issue {1}".format(new_status, self.link(issue_id)))

        # Prepare POST body
        transition_data = {
            "transition": {
                "id": wanted_transaction
            }
        }

        if summary is not None:
            transition_data.update({
                "summary": [
                    {
                        "set": summary
                    }
                ]
            })

        # Perform transition
        response = request.post(issue_url + "/transitions?expand=transitions.fields", self._serialize(transition_data),
                                contentType='application/json', headers=self._createApiTokenHeader())

        if response.status != 204:
            error(u"Unable to perform transition {0} for issue {1}".format(wanted_transaction, self.link(issue_id)), response)

    def _createRequest(self):
        params = self.jira_server.copy()
        if params['apiToken']:
            params.pop('username')
            params.pop('password')
        if self.username and self.password and not self.api_token:
            params['username'] = self.username
            params['password'] = self.password
        return HttpRequest(params)

    def _createApiTokenHeader(self):
        headers = None
        if self.api_token and self.username:
            headers = {'Authorization': 'Basic %s' % b64encode('%s:%s' % (self.username, self.api_token))}
        elif self.password and self.username:
            headers = None
        elif self.jira_server['apiToken']:
            headers = {'Authorization': 'Basic %s' % b64encode('%s:%s' % (self.jira_server['username'], self.jira_server['apiToken']))}
        return headers

    def link(self, issue_id):
        return "[{0}]({1}/browse/{0})".format(issue_id, self.jira_server['url'])

    def _issueUrl(self, issue_id):
        return self._getVersionUri() + "/issue/" + issue_id
    
    def _issueAssignUrl(self, issue_id):
            return self._getVersionUri() + "/issue/" + issue_id + "/assignee"

    def _checkIssue(self, issue_id):
        request = self._createRequest()
        response = request.get(self._issueUrl(issue_id),
                               contentType='application/json', headers=self._createApiTokenHeader())

        if response.status != 200:
            error(u"Unable to find issue {0}".format(self.link(issue_id)), response)

    def _versionsUrl(self, projectId):
        return self._getVersionUri() + "/project/%s/versions" % projectId

    def _serialize(self, content):
        return Json.dumps(content).encode(self.encoding)

    def _getHostingOption(self):
        if self.api_token and self.username:
            hosting_option = 'CLOUD'
        elif self.password and self.username:
            hosting_option = 'SERVER'
        elif self.jira_server['apiToken']:
            hosting_option = 'CLOUD'
        else:
            hosting_option = 'SERVER'

        return hosting_option

    def _getVersionUri(self):
        if self.hosting_option == 'SERVER':
            api_version_uri = '/rest/api/2'
        else:
            api_version_uri = '/rest/api/latest'


        return api_version_uri
