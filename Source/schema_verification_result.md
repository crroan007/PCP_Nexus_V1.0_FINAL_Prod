# Database Schema Guide

## Table: `jobs`
| CID | Name | Type | PK |
|---|---|---|---|
| 0 | **id** | INTEGER | KEY |
| 1 | **filename** | TEXT |  |
| 2 | **file_path** | TEXT |  |
| 3 | **status** | TEXT |  |
| 4 | **original_source** | TEXT |  |
| 5 | **locked_by** | TEXT |  |
| 6 | **locked_at** | TIMESTAMP |  |
| 7 | **processing_node_info** | TEXT |  |
| 8 | **created_at** | TIMESTAMP |  |
| 9 | **updated_at** | TIMESTAMP |  |
| 10 | **logs** | TEXT |  |
| 11 | **service_type** | TEXT |  |
| 12 | **workflow_log** | TEXT |  |
| 13 | **metadata** | TEXT |  |
| 14 | **action_flag** | INTEGER |  |
| 15 | **raw_comments** | TEXT |  |
| 16 | **file_hash** | TEXT |  |

## Table: `sqlite_sequence`
| CID | Name | Type | PK |
|---|---|---|---|
| 0 | **name** |  |  |
| 1 | **seq** |  |  |

