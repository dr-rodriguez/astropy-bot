import os
import json

from flask import Flask, request

from werkzeug.contrib.fixers import ProxyFix

from changebot.changelog import check_changelog_consistency
from changebot.github_api import RepoHandler, PullRequestHandler


app = Flask('astropy-bot')
app.wsgi_app = ProxyFix(app.wsgi_app)
app.integration_id = int(os.environ['GITHUB_APP_INTEGRATION_ID'])
app.private_key = os.environ['GITHUB_APP_PRIVATE_KEY']


@app.route("/")
def index():
    return "Nothing to see here"


@app.route("/installation_authorized")
def installation_authorized():
    return "Installation authorized"


@app.route("/hook", methods=['POST'])
def hook():

    event = request.headers['X-GitHub-Event']

    if event not in ('pull_request', 'issues'):
        return "Not a pull_request or issues event"

    # Parse the JSON sent by GitHub
    payload = json.loads(request.data)

    if 'installation' not in payload:
        return "No installation key found in payload"
    else:
        installation = payload['installation']['id']

    # We only need to listen to certain kinds of events:
    if event == 'pull_request':
        if payload['action'] not in ('unlabeled', 'labeled', 'synchronize', 'opened'):
            return 'Action \'' + payload['action'] + '\' does not require action'
    elif event == 'issues':
        if payload['action'] not in ('milestoned', 'demilestoned'):
            return 'Action \'' + payload['action'] + '\' does not require action'

    if event == 'pull_request':
        number = payload['pull_request']['number']
    elif event == 'issues':
        number = payload['issue']['number']
    else:
        return

    # TODO: cache handlers and invalidate the internal cache of the handlers on
    # certain events.
    pr_handler = PullRequestHandler(payload['repository']['full_name'], number, installation)

    repo_handler = RepoHandler(pr_handler.head_repo_name,
                               pr_handler.head_branch, installation)

    # Run checks
    # TODO: in future, make this more generic so that any checks can be run.
    # we could have a registry of checks and concatenate the responses
    issues = check_changelog_consistency(repo_handler, pr_handler)

    # Find previous comments by this app
    comment_ids = pr_handler.find_comments('astropy-bot[bot]')

    if len(comment_ids) == 0:
        comment_id = None
    else:
        comment_id = comment_ids[-1]
    # Construct message

    message = (f'Hi there @{pr_handler.user} :wave: - thanks for the pull request! '
               'I\'m just a friendly :robot: that checks for '
               'issues related to the changelog and making sure that this '
               'pull request is milestoned and labelled correctly. This is '
               'mainly intended for the maintainers, so if you are not '
               'a maintainer you can ignore this, and a maintainer will let '
               'you know if any action is required on your part :smiley:.\n\n')

    if 'Work in progress' in pr_handler.labels:
        message += ("I see this is a work in progress pull request. I'll "
                    "report back on the checks once the PR is ready for review.")
        
    elif 'Experimental' in pr_handler.labels:
        message += ("I see this is an experimental pull request. I'll "
                    "report back on the checks once the PR discussion in settled.")

    elif len(issues) > 0:

        message += "I noticed the following issues with this pull request:\n\n"
        for issue in issues:
            message += "* {0}\n".format(issue)

        message += "\nWould it be possible to fix these? Thanks! \n"

        if len(issues) == 1:
            message = (message.replace('issues with', 'issue with')
                       .replace('fix these', 'fix this'))

    else:

        message += "Everything looks good from my point of view! :+1:"

    pr_handler.submit_comment(message, comment_id=comment_id)

    if len(issues) == 0:
        pr_handler.set_status('success', 'All checks passed', 'astropy-bot')
    else:
        pr_handler.set_status('failure', 'There were failures in checks - see '
                                         'comments by @astropy-bot above',
                                         'astropy-bot')

    return message
