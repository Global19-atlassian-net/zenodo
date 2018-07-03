# -*- coding: utf-8 -*-
#
# This file is part of Zenodo.
# Copyright (C) 2016 CERN.
#
# Zenodo is free software; you can redistribute it
# and/or modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 2 of the
# License, or (at your option) any later version.
#
# Zenodo is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Zenodo; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place, Suite 330, Boston,
# MA 02111-1307, USA.
#
# In applying this license, CERN does not
# waive the privileges and immunities granted to it by virtue of its status
# as an Intergovernmental Organization or submit itself to any jurisdiction.

"""Record modification prior to indexing."""

from __future__ import absolute_import, print_function

from invenio_pidrelations.contrib.versioning import PIDVersioning
from invenio_pidrelations.proxies import current_pidrelations
from invenio_pidrelations.serializers.utils import serialize_relations
from invenio_pidstore.models import PersistentIdentifier
from invenio_stats import current_stats

from zenodo.modules.records.serializers.pidrelations import \
    serialize_related_identifiers


def _build_stats(record, skip_files=False):
    stats = {}
    stats_sources = {
        'record-view': {
            'params': {'recid': record['recid']},
            'fields': {
                'views': 'count',
                'unique_views': 'unique_count',
            },
        },
        'record-download': {
            'files_related': True,
            'params': {'recid': record['recid']},
            'fields': {
                'downloads': 'count',
                'unique_downloads': 'unique_count',
                'volume': 'volume',
            },
        },
        'record-view-all-versions': {
            'params': {'conceptrecid': record.get('conceptrecid')},
            'fields': {
                'version_views': 'count',
                'version_unique_views': 'unique_count',
            }
        },
        'record-download-all-versions': {
            'files_related': True,
            'params': {'conceptrecid': record.get('conceptrecid')},
            'fields': {
                'version_downloads': 'count',
                'version_unique_downloads': 'unique_count',
                'version_volume': 'volume',
            },
        },
    }
    for query_name, cfg in stats_sources.items():
        if cfg.get('files_related') and skip_files:
            continue
        try:
            query_cfg = current_stats.queries[query_name]
            query = query_cfg.query_class(**query_cfg.query_config)
            result = query.run(**cfg['params'])
            for dst, src in cfg['fields'].items():
                stats[dst] = result.get(src)
        except Exception:
            pass
    return stats


def indexer_receiver(sender, json=None, record=None, index=None,
                     **dummy_kwargs):
    """Connect to before_record_index signal to transform record for ES."""
    if not index.startswith('records-') or record.get('$schema') is None:
        return

    # Remove files from index if record is not open access.
    if json['access_right'] != 'open' and '_files' in json:
        del json['_files']
    else:
        # Compute file count and total size
        files = json.get('_files', [])
        json['filecount'] = len(files)
        json['size'] = sum([f.get('size', 0) for f in files])

    pid = PersistentIdentifier.query.filter(
        PersistentIdentifier.object_uuid == record.id,
        PersistentIdentifier.pid_type == current_pidrelations.primary_pid_type,
        ).one_or_none()
    if pid:
        pv = PIDVersioning(child=pid)
        if pv.exists:
            relations = serialize_relations(pid)
        else:
            relations = {'version': [{'is_last': True, 'index': 0}, ]}
        if relations:
            json['relations'] = relations

        rels = serialize_related_identifiers(pid)
        if rels:
            json.setdefault('related_identifiers', []).extend(rels)

    # Remove internal data.
    if '_internal' in json:
        del json['_internal']

    json['_stats'] = _build_stats(
        record, skip_files=json['access_right'] != 'open')
