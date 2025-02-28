from pathlib import Path
from flask import Flask, request, url_for
import htmlfn as hfn
from htmlfn import htmldoc, atag
from htmlfn import table_style, navbar_style
from sparcur import pipelines as pipes
from sparcur.curation import Integrator


def nowrap(class_, tag=''):
    return (f'{tag}.{class_}'
            '{ white-space: nowrap; }')


def wrap_tables(*tables, title=None):
    return htmldoc(*tables,
                   styles=(table_style, nowrap('td', 'col-id')),
                   title=title)


def make_app(self, name='spc-server'):
    """ self is a sparcur.cli.Main """
    app = Flask(name)
    yield app

    bp = '/dashboard'

    @app.route(f'{bp}/datasets')
    def route_datasets(id):
        table, title = self._print_paths(self.project_path.children)
        return wrap_tables(table, title=title)

    @app.route(f'{bp}/datasets/<id>')
    def route_datasets_id(id):
        if id not in self.dataset_index:
            return abort(404)

        dataset = self.dataset_index[id]
        tables = []
        try:
            ddt = [['TO', 'DO'], [id, 'derive tables from curation export!']]
            table, _ = self._print_table(ddt)
            tables.append(table)
        except StopIteration:
            return abort(404)  # FIXME ... no data instead plus iterate

        return wrap_tables(*tables, title='Dataset metadata tables')

    @app.route(f'{bp}/reports')
    @app.route(f'{bp}/reports/')
    def route_reports():
        report_names = (
            'completeness',
            'size',
            'filetypes',
            'pathids',
            'keywords',
            'subjects',
            'errors',
            'terms',
        )
        report_links = [atag(url_for(f'route_reports_{rn}', ext=None), rn) + '<br>\n'
                        for rn in report_names]
        return htmldoc('Reports<br>\n',
                       *report_links,
                       title='Reports')

    @app.route(f'{bp}/reports/completeness')
    @app.route(f'{bp}/reports/completeness<ext>')
    def route_reports_completeness(ext=wrap_tables):
        return self.report.completeness(ext=ext)

    @app.route(f'{bp}/reports/size')
    @app.route(f'{bp}/reports/size<ext>')
    def route_reports_size(ext=wrap_tables):
        return self.report.size(dirs=self.project_path.children, ext=ext)

    @app.route(f'{bp}/reports/filetypes')
    @app.route(f'{bp}/reports/filetypes<ext>')
    def route_reports_filetypes(ext=None):
        if ext is not None:  # TODO
            return 'Not found', 404

        tables = []
        for table, title in self.report.filetypes():
            tables.append(table + '<br>\n')

        return wrap_tables(*tables, title='Filetypes')

    @app.route(f'{bp}/reports/pathids')
    @app.route(f'{bp}/reports/pathids<ext>')
    def route_reports_pathids(ext=wrap_tables):
        return self.report.pathids(ext=ext)

    @app.route(f'{bp}/reports/keywords')
    @app.route(f'{bp}/reports/keywords<ext>')
    def route_reports_keywords(ext=wrap_tables):
        return self.report.keywords(ext=ext)

    @app.route(f'{bp}/reports/subjects')
    @app.route(f'{bp}/reports/subjects<ext>')
    def route_reports_subjects(ext=wrap_tables):
        return self.report.subjects(ext=ext)

    @app.route(f'{bp}/reports/errors')
    @app.route(f'{bp}/reports/errors<ext>')
    def route_reports_errors(ext=wrap_tables):
        return 'TODO'
        table, title = self.report.errors()
        return wrap_tables(table, title=title)

    @app.route(f'{bp}/reports/terms')
    @app.route(f'{bp}/reports/terms<ext>')
    def route_reports_terms(ext=None):
        if ext is not None:  # TODO
            return 'Not found', 404

        tables = []
        for table, title in self.report.terms():
            tables.append(table + '<br>\n')

        return wrap_tables(*tables, title='Terms')


    @app.route(f'{bp}/apinat/demo')
    @app.route(f'{bp}/apinat/demo<ext>')
    def route_apinat_demo(ext=None):
        source = Path('~/ni/sparc/apinat/sources/').expanduser()  # FIXME config probably
        rm = pipes.ApiNATOMY(source / 'apinatomy-resourceMap.json')
        r = pipes.ApiNATOMY_rdf(rm.data)  # FIXME ... should be able to pass the pipeline
        if ext == '.ttl':
            return r.data.ttl, 200, {'Content-Type': 'text/turtle; charset=utf-8',}

        return hfn.htmldoc(r.data.ttl_html,
                           styles=(hfn.ttl_html_style,),
                           title='ApiNATOMY demo')
