---
description: 'System table containing information about the number of events that
  have occurred in the system.'
keywords: ['system table', 'events']
slug: /operations/system-tables/events
title: 'system.events'
---

import SystemTableCloud from '@site/docs/_snippets/_system_table_cloud.md';

<SystemTableCloud/>

Contains information about the number of events that have occurred in the system. For example, in the table, you can find how many `SELECT` queries were processed since the ClickHouse server started.

Columns:

- `event` ([String](../../sql-reference/data-types/string.md)) — Event name.
- `value` ([UInt64](../../sql-reference/data-types/int-uint.md)) — Number of events occurred.
- `description` ([String](../../sql-reference/data-types/string.md)) — Event description.
- `name` ([String](../../sql-reference/data-types/string.md)) — Alias for `event`.

You can find all supported events in source file [src/Common/ProfileEvents.cpp](https://github.com/ClickHouse/ClickHouse/blob/master/src/Common/ProfileEvents.cpp).

**Example**

```sql
SELECT * FROM system.events LIMIT 5
```

```text
┌─event─────────────────────────────────┬─value─┬─description────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Query                                 │    12 │ Number of queries to be interpreted and potentially executed. Does not include queries that failed to parse or were rejected due to AST size limits, quota limits or limits on the number of simultaneously running queries. May include internal queries initiated by ClickHouse itself. Does not count subqueries.                  │
│ SelectQuery                           │     8 │ Same as Query, but only for SELECT queries.                                                                                                                                                                                                                │
│ FileOpen                              │    73 │ Number of files opened.                                                                                                                                                                                                                                    │
│ ReadBufferFromFileDescriptorRead      │   155 │ Number of reads (read/pread) from a file descriptor. Does not include sockets.                                                                                                                                                                             │
│ ReadBufferFromFileDescriptorReadBytes │  9931 │ Number of bytes read from file descriptors. If the file is compressed, this will show the compressed data size.                                                                                                                                              │
└───────────────────────────────────────┴───────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**See Also**

- [system.asynchronous_metrics](/operations/system-tables/asynchronous_metrics) — Contains periodically calculated metrics.
- [system.metrics](/operations/system-tables/metrics) — Contains instantly calculated metrics.
- [system.metric_log](/operations/system-tables/metric_log) — Contains a history of metrics values from tables `system.metrics` and `system.events`.
- [Monitoring](../../operations/monitoring.md) — Base concepts of ClickHouse monitoring.
