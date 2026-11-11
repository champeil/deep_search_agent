"""Prepare local public metadata and a market submission draft. Never publishes."""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]

def repository(value):
    value=value.strip().removesuffix('.git').rstrip('/')
    if value.startswith('https://github.com/'):
        parsed=urlsplit(value)
        if parsed.query or parsed.fragment:raise ValueError('Use a repository URL without query or fragment')
        value=parsed.path.strip('/')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}',value):
        raise ValueError('Expected owner/repo or https://github.com/owner/repo')
    return value


def prepare(repo,author=None,root=ROOT,dry_run=False):
    repo=repository(repo)
    root=Path(root)
    manifest=json.loads((root/'package.json').read_text(encoding='utf-8'))
    url='https://github.com/'+repo
    manifest['repository']={'type':'git','url':'git+'+url+'.git'}
    manifest['homepage']=url+'#readme'
    manifest['bugs']={'url':url+'/issues'}
    if author:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}',author):raise ValueError('Use an actual GitHub username')
        manifest['author']={'name':author,'url':'https://github.com/'+author}
    result={'repository':url,'package':manifest['name'],'version':manifest['version'],
            'topics':['dsh-plugin','deepseek-harness','cordis-plugin','deep-research'],
            'install_command':'dsh plugin --profile web add github:'+repo,
            'market':'https://plugin.dshdesk.com/publish','github_username':author,
            'description':'多领域深度研究工作流：原生搜索优先、全文优先阅读、数据库检索、逐条证据与引用审阅、请求预算及覆盖记录；使用当前宿主模型。',
            'ownership_attestation_required':True,'public_submission_notice':'Repository, description and submission notes become public on the community registry review issue.',
            'status':'local_draft_only','published':False}
    if not dry_run:
        # Preserve exact current metadata before changing only publication fields.
        path=root/'package.json'
        backup=path.with_name('package.json.before-publish.backup')
        if not backup.exists():backup.write_text(path.read_text(encoding='utf-8'),encoding='utf-8')
        path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (root/'DSH_SUBMISSION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',required=True)
    parser.add_argument('--author')
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    try:print(json.dumps(prepare(args.repo,args.author,dry_run=args.dry_run),ensure_ascii=False,indent=2))
    except ValueError as exc:parser.exit(1,str(exc)+'\n')
