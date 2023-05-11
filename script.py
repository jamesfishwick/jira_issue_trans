from jira import JIRA
from dotenv import load_dotenv
import os
import datetime
import requests
import json
import base64

load_dotenv()

JIRA_URL = os.getenv('JIRA_URL')
JIRA_USERNAME = os.getenv('JIRA_USERNAME')
JIRA_API_TOKEN = os.getenv('JIRA_API_TOKEN')
JIRA_FILTER_ID = os.getenv('JIRA_FILTER_ID')

jira = JIRA(JIRA_URL, basic_auth=(JIRA_USERNAME, JIRA_API_TOKEN))


def get_status_durations(histories, forced_start_date=None):
    status_durations = {}
    status_start_times = {}
    dev_in_progress_encountered = False

    for history in histories:
        for item in history['items']:
            if item['field'] == 'status':
                status_from = item['fromString']
                status_to = item['toString']

                if not dev_in_progress_encountered and (forced_start_date is not None or status_to == 'Dev In Progress'):
                    dev_in_progress_encountered = True

                if dev_in_progress_encountered:
                    timestamp = datetime.datetime.strptime(
                        history['created'][:19], '%Y-%m-%dT%H:%M:%S')

                    if forced_start_date is not None:
                        forced_start_date = datetime.datetime.strptime(
                            forced_start_date, '%Y-%m-%d')
                        status_start_times[status_to] = forced_start_date
                        forced_start_date = None
                    else:
                        if status_from not in status_start_times:
                            status_start_times[status_from] = timestamp
                        else:
                            transition = (status_from, status_to)
                            if transition not in status_durations:
                                status_durations[transition] = {
                                    'total_duration': datetime.timedelta(), 'count': 0}

                            status_durations[transition]['total_duration'] += timestamp - \
                                status_start_times[status_from]
                            status_durations[transition]['count'] += 1
                            status_start_times[status_from] = timestamp

    return status_durations


def get_all_histories(issue_key, jira_url, jira_username, jira_api_token):
    all_histories = []
    start_at = 0
    max_results = 50

    auth_string = f'{jira_username}:{jira_api_token}'
    auth_encoded = base64.b64encode(auth_string.encode()).decode('ascii')

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Basic {auth_encoded}'
    }

    while True:
        url = f'{jira_url}/rest/api/2/issue/{issue_key}/changelog?startAt={start_at}&maxResults={max_results}'
        response = requests.get(url, headers=headers)
        data = json.loads(response.text)

        if response.status_code != 200:
            print(
                f"Error fetching changelog for issue {issue_key}: {response.text}")
            return []

        histories = data['values']

        if not histories:
            break

        all_histories.extend(histories)
        start_at += max_results

    return all_histories


def workdays_between_dates(start_date, end_date):
    workdays = 0
    date_iterator = start_date

    while date_iterator <= end_date:
        if date_iterator.weekday() < 5:  # Weekday (Mon-Fri)
            workdays += 1
        date_iterator += datetime.timedelta(days=1)

    return workdays


def get_transition_dates(issue_key, jira_url, jira_username, jira_api_token):
    histories = get_all_histories(
        issue_key, jira_url, jira_username, jira_api_token)

    start_date = None
    end_date = None

    for history in histories:
        for item in history['items']:
            if item['field'] == 'status':
                if item['toString'] == 'Dev In Progress':
                    start_date = datetime.datetime.strptime(
                        history['created'][:10], '%Y-%m-%d').date()
                if item['toString'] == 'Done' and start_date is not None:
                    end_date = datetime.datetime.strptime(
                        history['created'][:10], '%Y-%m-%d').date()

                    # Return the start and end dates as soon as they are found
                    return start_date, end_date

    # Return None for start and end dates if the transitions are not found
    return None, None


def get_all_issues(jira, filter_id):
    all_issues = []
    start_at = 0
    max_results = 50

    while True:
        issues = jira.search_issues(
            f'filter={filter_id}', startAt=start_at, maxResults=max_results)

        if not issues:
            break

        all_issues.extend(issues)
        start_at += max_results

    return all_issues


issues = get_all_issues(jira, JIRA_FILTER_ID)
story_point_data = {}
all_status_durations = {}
total_story_points = 0
total_workdays = 0
workdays = 0

for issue in issues:
    start_date, end_date = get_transition_dates(
        issue.key, JIRA_URL, JIRA_USERNAME, JIRA_API_TOKEN)
    story_points = issue.fields.customfield_10030

    try:
        story_points = int(story_points)
    except (ValueError, TypeError):
        story_points = 0

    if start_date and end_date:
        workdays = workdays_between_dates(start_date, end_date)
        print(
            f"Issue {issue.key} took {workdays} workdays to complete and has {(story_points)} Story Points.")
    else:
        print(
            f"Issue {issue.key} does not have the required transitions and has {(story_points)} Story Points.")

    if story_points not in story_point_data:
        story_point_data[story_points] = {'total_days': 0, 'count': 0}

    story_point_data[story_points]['total_days'] += workdays
    story_point_data[story_points]['count'] += 1
    total_story_points += story_points
    total_workdays += workdays

    histories = get_all_histories(
        issue.key, JIRA_URL, JIRA_USERNAME, JIRA_API_TOKEN)
    status_durations = get_status_durations(histories)

    for transition, data in status_durations.items():
        if transition not in all_status_durations:
            all_status_durations[transition] = {
                'total_duration': datetime.timedelta(), 'count': 0}

        all_status_durations[transition]['total_duration'] += data['total_duration']
        all_status_durations[transition]['count'] += data['count']

average_time_per_story_point = total_workdays / total_story_points
print(f"\nTotal Story Points: {total_story_points}")
print(
    f"Average Time per Story Point: {average_time_per_story_point:.2f} workdays")
print(f"Average Points per Story: {total_story_points / len(issues):.2f}")
print(f"Average Days per Story: {total_workdays / len(issues):.2f}")
print("\nAverage time spent in each transition:")
for transition, data in all_status_durations.items():
    average_duration = data['total_duration'] / data['count']
    print(f"{transition[0]} -> {transition[1]}: {average_duration}")
print("\nAverage Days taken for each Story Point value:")
for story_points, data in sorted(story_point_data.items()):
    average_days = data['total_days'] / data['count']
    print(f"{story_points} Story Points: {average_days:.2f} days")
