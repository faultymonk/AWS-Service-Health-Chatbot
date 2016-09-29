#!/usr/bin/env python

import boto3
import hashlib
import json
import re
import requests
from lxml import html
from unicodedata import normalize

def sdb_get_status(domain_name='aws-status', region='us-west-2', item_name='status', attribute_name='last'):
  sdb = boto3.client('sdb', region_name=region)
  resp = sdb.get_attributes(DomainName=domain_name, ItemName=item_name, AttributeNames=[
    attribute_name
  ], ConsistentRead=False)
  return resp['Attributes'][0]['Value']

def sdb_put_status(msg, domain_name='aws-status', region='us-west-2', item_name='status', attribute_name='last'):
  sdb = boto3.client('sdb', region_name=region)
  # output: None
  sdb.put_attributes(DomainName=domain_name, ItemName=item_name, Attributes=[{
    'Name': attribute_name,
    'Value': msg,
    'Replace': True
  }])

def md5_hash(string_text):
  md5 = hashlib.md5()
  md5.update(string_text)
  return md5.hexdigest()

def post_to_webhook(url, msg, msg_format='', auth_token=None):
  headers = {'Content-Type': 'application/json'}
  if msg_format == 'hipchat':
    params = {'auth_token': auth_token}
    data = json.dumps({'message': json.dumps(msg, indent=4), 'notify': True, 'message_format': 'text', 'color': 'red'})
  elif msg_format == 'slack':
    params = None
    data = json.dumps({"attachments": [{
      "color": "#DF1A22",
      "title": "AWS Health Dashboard",
      "title_link": "http://status.aws.amazon.com/",
      "text": json.dumps(msg, indent=4)
    }]})
  return requests.post(url, params=params, headers=headers, data=data)

def scrape_url(url='http://status.aws.amazon.com/'):
  page = requests.get(url)
  tree = html.fromstring(page.content)
  # grab just the tables
  tables = tree.xpath('//tbody')
  # four tables on page, so zip
  continent = ['North America', 'South America', 'Europe', 'Asia']
  statuses = dict(zip(continent, tables))
  scraped = {}
  for continent, table in statuses.iteritems():
    events = []
    for x in table.getchildren():
      if not ( 'Service is operating normally' in x.text_content() ):
        # munge for better legibility, split by time (e.g. 7:47 AM PDT\xa0)
        event = re.sub("([A-z]{3} \d{1,2}, )?(\d{1,2}:\d{1,2} .M)( .{3})\xa0", r'\n\2\3 - ', re.sub(' +', ' ', re.sub(r'\n {6}', '', re.sub(u'\xa0{4}[a-z]{4}.', '', x.text_content().strip().replace('\r\n',' '))))).split('\n')
        # munge each service into dicts by time
        events.append({event[0].strip(): map(unicode.strip, event[1:])})
    if events:
      scraped[continent] = events
  if scraped:
    return scraped

def lambda_handler(event, context):
  # define channel config
  url = 'https://Webhook_URL'
  # slack: auth_token = None
  auth_token = None
  msg_format = 'slack'
  # begin scrape
  resp = scrape_url()
  if resp:
    old_resp = sdb_get_status()
    # sdb attribute limit of 1024, so store ~unique hash instead
    curr_resp = md5_hash(str(json.dumps(resp)))
    if curr_resp != old_resp:
      sdb_put_status(curr_resp)
      post_to_webhook(url, resp, msg_format=msg_format, auth_token=auth_token)
      print(json.dumps(resp, indent=4))
  else:
    sdb_put_status('None')
    print('all is well')
  # return response for api gateway
  return resp
