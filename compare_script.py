import json
import requests
from requests.auth import HTTPBasicAuth
from difflib import HtmlDiff
import xml.etree.ElementTree as ET

# Load config
with open('config.json') as f:
    config = json.load(f)

instances = {inst['name']: inst for inst in config['instances']}
instance_names = list(instances.keys())

print("Available instances:")
for idx, name in enumerate(instance_names, 1):
    print(f"{idx}. {name}")

def select_instance(prompt):
    while True:
        choice = input(prompt)
        if choice.isdigit() and 1 <= int(choice) <= len(instance_names):
            return instances[instance_names[int(choice) - 1]]
        print(f"Invalid input. Enter a number between 1 and {len(instance_names)}.")

source = select_instance("Select source instance number: ")
target = select_instance("Select target instance number: ")

if source['name'] == target['name']:
    print("Warning: Source and target are the same instance!")

TABLES = config.get('tables', [])
QUERY = config.get('query', '')

def get_records(instance, table, query=''):
    print(f"[INFO] Fetching records from {instance['name']} ({table}) with query: '{query}'")
    resp = requests.get(
        f"{instance['host']}/api/now/table/{table}",
        auth=HTTPBasicAuth(instance['user'], instance['pass']),
        params={'sysparm_query': query, 'sysparm_limit': 100}
    )
    resp.raise_for_status()
    results = resp.json().get('result', []) or []
    print(f"[INFO] Retrieved {len(results)} records from {instance['name']}:{table}")
    return results

def get_record_xml(instance, table, sys_id):
    print(f"[INFO] Downloading XML for sys_id={sys_id} from {instance['name']}:{table}")
    resp = requests.get(
        f"{instance['host']}/{table}.do?XML=&sys_id={sys_id}",
        auth=HTTPBasicAuth(instance['user'], instance['pass'])
    )
    resp.raise_for_status()
    return resp.text

def parse_xml(xml_text):
    root = ET.fromstring(xml_text)
    data = {c.tag: (c.text or "") for c in root.findall(".//*") if c.tag != "xml"}
    print(f"[DEBUG] Parsed XML with {len(data)} fields")
    return data

def diff_html(val1, val2):
    differ = HtmlDiff(wrapcolumn=80)
    html_diff = differ.make_table(
        val1.splitlines() if val1 else [],
        val2.splitlines() if val2 else [],
        context=False,  # Show full diff without collapsing lines
        numlines=0
    )
    print("[DEBUG] Generated HTML diff")
    return html_diff

def looks_like_javascript(text):
    js_indicators = ['function', 'var ', 'let ', 'const ', '=>', 'console.', 'if(', 'for(', 'while(', '{', '}', ';']
    text_lower = text.lower()
    return any(ind in text_lower for ind in js_indicators)

def wrap_html(content):
    return f"""
<html><head><title>ServiceNow Diff Report</title>
<link href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css" rel="stylesheet">
<style>
table.table tbody tr.changed-row {{
  background-color: #ffecec !important;
}}
pre {{
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 300px;
  overflow: auto;
}}
.diff table {{
  width: 100%;
  border-collapse: collapse;
}}
.diff td {{
  vertical-align: top;
  padding: 4px;
  font-family: monospace;
  font-size: 0.8rem;
}}
.diff .diff_header {{
  background: #eee;
}}
.diff .diff_add {{
  background: #cfc;
}}
.diff .diff_sub {{
  background: #fcc;
}}
</style></head><body class="p-3">
<h1>ServiceNow Comparison Report</h1>
<p><strong>Comparing:</strong> {source['name']} ({source['host']}) <em>vs</em> {target['name']} ({target['host']})</p>
<div class="mb-2">
<button class="btn btn-sm btn-primary" onclick="filterAll()">Show All</button>
<button class="btn btn-sm btn-danger" onclick="filterChanged()">Show Changed</button>
<button class="btn btn-sm btn-secondary" onclick="filterUnchanged()">Show Unchanged</button>
</div>
{content}
<script>
function filterAll() {{
  document.querySelectorAll('tr[data-status]').forEach(r => r.style.display = '');
  document.querySelectorAll('[data-record-status]').forEach(r => r.style.display = '');
}}
function filterChanged() {{
  document.querySelectorAll('tr[data-status]').forEach(r => r.style.display = r.dataset.status === 'changed' ? '' : 'none');
  document.querySelectorAll('[data-record-status]').forEach(r => r.style.display = r.dataset.recordStatus === 'changed' ? '' : 'none');
}}
function filterUnchanged() {{
  document.querySelectorAll('tr[data-status]').forEach(r => r.style.display = r.dataset.status === 'unchanged' ? '' : 'none');
  document.querySelectorAll('[data-record-status]').forEach(r => r.style.display = r.dataset.recordStatus === 'unchanged' ? '' : 'none');
}}
function openModal(id) {{
  new bootstrap.Modal(document.getElementById(id)).show();
}}
</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/js/bootstrap.bundle.min.js"></script>
</body></html>"""

summary_rows = ""
detail_html = ""

for TABLE in TABLES:
    print(f"[INFO] Processing table: {TABLE}")
    summary_rows += f"<tr><th colspan='3'>Table: {TABLE}</th></tr>"
    source_records = get_records(source, TABLE, QUERY)
    for record in source_records:
        sys_id = record['sys_id']
        name = record.get('name') or record.get('short_description') or sys_id
        print(f"[INFO] Comparing record '{name}' (sys_id={sys_id})")
        xml1 = get_record_xml(source, TABLE, sys_id)
        xml2 = get_record_xml(target, TABLE, sys_id)
        data1 = parse_xml(xml1)
        data2 = parse_xml(xml2)
        record_id = name.replace(' ', '_').replace('.', '_')
        detail_rows = ""
        modals_html = ""
        diff_count = 0
        for key in sorted(set(data1.keys()) | set(data2.keys())):
            val1, val2 = data1.get(key, ""), data2.get(key, "")
            status = "unchanged"
            if val1 != val2:
                status = "changed"
                diff_count += 1
                print(f"[DEBUG] Field changed: {key}")
            row_class = "changed-row" if status == "changed" else ""

            # Show 'Show Script' button only for changed fields containing JS code
            if ("script" in key.lower() and val1 != val2 and
                not (val1.lower() in ['true','false'] or val2.lower() in ['true','false']) and
                (looks_like_javascript(val1) or looks_like_javascript(val2))):
                diff_html_content = diff_html(val1, val2)
                popup_id = f"{record_id}_{key}"
                detail_rows += f"""
<tr data-status="{status}" class="{row_class}">
  <td>{key}</td>
  <td colspan="2"><button class="btn btn-sm btn-primary" onclick="openModal('{popup_id}')">Show Script</button></td>
  <td>{status}</td>
</tr>"""
                modals_html += f"""
<div class="modal fade" id="{popup_id}" tabindex="-1">
  <div class="modal-dialog modal-xl modal-dialog-scrollable">
    <div class="modal-content" style="max-height:80vh; overflow:auto; padding:1rem;" class="diff">
      {diff_html_content}
    </div>
  </div>
</div>"""
            else:
                detail_rows += f"""
<tr data-status="{status}" class="{row_class}">
  <td>{key}</td>
  <td>{val1}</td>
  <td>{val2}</td>
  <td>{status}</td>
</tr>"""
        record_status = "changed" if diff_count > 0 else "unchanged"
        summary_rows += f"<tr><td>{name}</td><td>{diff_count}</td><td><a href='#record-{record_id}'>Jump</a></td></tr>"
        detail_html += f"""
<div id="record-{record_id}" class="my-4" data-record-status="{record_status}">
<h3>{name}</h3>
<table class="table table-bordered table-sm">
<thead><tr><th>Field</th><th>Source ({source['host']})</th><th>Target ({target['host']})</th><th>Status</th></tr></thead>
<tbody>{detail_rows}</tbody></table>
{modals_html}
</div>"""

summary_table_html = f"""
<table class="table table-bordered table-sm">
<thead><tr><th>Name</th><th>Diff Count</th><th>Link</th></tr></thead><tbody>{summary_rows}</tbody></table>"""

report_html = wrap_html(summary_table_html + detail_html)

with open('comparison_report.html', 'w', encoding='utf-8') as f:
    f.write(report_html)

print("✅ comparison_report.html generated!")
