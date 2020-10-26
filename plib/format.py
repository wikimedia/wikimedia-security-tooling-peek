import copy


def tasks_summary_header(tasks_summary, duration_header='days'):
    """create dicts for sane table building in html

    TODO: This is cleaner in the presentation layer,
    however my masochism for jinja2 templates
    has now exceeded my pragmatism quotient.
    """

    headers = {}
    # The same metric may have different columns in different
    # durations.  Make sure this is inclusive of all in order
    # for the table to be readable and consistent.  Durations
    # without a specific column value will be assigned a default
    # value later on.
    for metric_set in tasks_summary.values():
        for title, metric in metric_set['stats'].items():
            if title not in headers:
                headers[title] = []
                headers[title] += sorted(list(metric.keys()))
            else:
                headers[title] = sorted(list(set(headers[title])))
    return headers


def tasks_summary_table(headers, tasks_summary):
    """create dicts for sane table building in html

    TODO: This is maybe cleaner in the presentation layer,
    however my masochism for jinja2 templates
    has now exceeded my pragmatism quotient.
    """
    # Reflow the stats summary from by duration to by attribute
    metrics_table = {}

    for k, v in headers.items():
        metrics_table[k] = {}
        metrics_table[k]['header'] = copy.deepcopy(v)
        metrics_table[k]['durations'] = {}

    for duration, metrics in tasks_summary.items():
        for stat_name, values in metrics['stats'].items():
            for table_name, table_row in metrics_table.items():
                if duration not in metrics_table[table_name]['durations']:
                    metrics_table[table_name]['durations'][duration] = []
                if stat_name == table_name:
                    for header in table_row['header']:
                        metrics_table[table_name]['durations'][duration].append(values.get(header) or 0)

    # Insert the header for durations themselves
    for table in metrics_table:
        metrics_table[table]['header'].insert(0, 'days')
    return metrics_table
