from __future__ import annotations

import argparse
import json
import sys

from .kernel import AIOSKernel


def output(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog='aios')
    sub = root.add_subparsers(dest='command')
    sub.add_parser('init')
    sub.add_parser('status')
    sub.add_parser('audit')

    project = sub.add_parser('project')
    ps = project.add_subparsers(dest='sub')
    add = ps.add_parser('add')
    add.add_argument('name')
    add.add_argument('path')
    add.add_argument('--language')
    ps.add_parser('list')

    workspace = sub.add_parser('workspace')
    ws = workspace.add_subparsers(dest='sub')
    create = ws.add_parser('create')
    create.add_argument('project')

    security = sub.add_parser('security')
    ss = security.add_subparsers(dest='sub')
    scan = ss.add_parser('scan')
    scan.add_argument('project')

    memory = sub.add_parser('memory')
    ms = memory.add_subparsers(dest='sub')
    remember = ms.add_parser('add')
    remember.add_argument('content')
    remember.add_argument('--project')
    remember.add_argument('--kind', default='note')
    search = ms.add_parser('search')
    search.add_argument('query')
    search.add_argument('--project')
    failure = ms.add_parser('failure')
    failure.add_argument('description')
    failure.add_argument('--project')

    analyze = sub.add_parser('analyze')
    analyze.add_argument('request')
    analyze.add_argument('--project')

    chat = sub.add_parser('chat')
    chat.add_argument('request')
    chat.add_argument('--project')

    council = sub.add_parser('council')
    council.add_argument('request')

    return root


def main() -> None:
    args = parser().parse_args()
    kernel = AIOSKernel()

    if args.command in (None, 'status'):
        output(kernel.status()); return
    if args.command == 'init':
        kernel.audit.record('system', 'initialize', 'success')
        output(kernel.status()); return
    if args.command == 'audit':
        output(kernel.audit.recent()); return
    if args.command == 'project':
        if args.sub == 'add':
            kernel.projects.add(args.name, args.path, args.language)
            print(f'Project added: {args.name}'); return
        if args.sub == 'list':
            output(kernel.projects.list()); return
    if args.command == 'workspace' and args.sub == 'create':
        print(kernel.projects.create_workspace(args.project)); return
    if args.command == 'security' and args.sub == 'scan':
        output([item.to_dict() for item in kernel.security.scan(args.project)]); return
    if args.command == 'memory':
        if args.sub == 'add':
            print(kernel.memory.remember(args.content, args.kind, args.project, 'cli')); return
        if args.sub == 'search':
            output(kernel.memory.search(args.query, args.project)); return
        if args.sub == 'failure':
            print(kernel.memory.record_failure(args.description, args.project)); return
    if args.command == 'analyze':
        output(kernel.analyze(args.request, args.project)); return
    if args.command == 'chat':
        print(kernel.chat(args.request, args.project)); return
    if args.command == 'council':
        output([{'expert': x.expert, 'opinion': x.opinion, 'priority': x.priority} for x in kernel.council.review(args.request)]); return

    parser().print_help()
    sys.exit(1)
