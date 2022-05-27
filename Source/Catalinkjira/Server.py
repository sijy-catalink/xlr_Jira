#
# Copyright 2020 CATALINK
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#

from base64 import b64encode
from org.apache.http.client import ClientProtocolException

global configuration

params = {'url': configuration.url, 'proxyHost': configuration.proxyHost, 'proxyPort': configuration.proxyPort,
          'proxyUsername': configuration.proxyUsername, 'proxyPassword': configuration.proxyPassword,
          'proxyDomain': configuration.proxyDomain}

response = None
try:
    headers = None
    apiVersionUri = ''
    if configuration.apiToken:
        auth = b64encode('%s:%s' % (configuration.username, configuration.apiToken))
        headers = {'Authorization': 'Basic %s' % auth}
        apiVersionUri = '/rest/api/latest'
    elif configuration.password:
        params['username'] = configuration.username
        params['password'] = configuration.password
        apiVersionUri = '/rest/api/2'
    response = HttpRequest(params).get(apiVersionUri + '/application-properties',
                                       contentType='application/json', headers=headers)
except ClientProtocolException:
    raise Exception("URL is not valid")

# Jira api returns 403 in case you are authenticated but not enough permissions
if response.status != 403 and response.status != 200:
    reason = "Unknown"
    if response.status == 400:
        reason = "Bad request"
    elif response.status == 401:
        reason = "Unauthorized"
    raise Exception("HTTP response code %s, reason %s" % (response.status, reason))

