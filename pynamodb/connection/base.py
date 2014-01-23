"""
Lowest level connection
"""
import six
from botocore.session import get_session

from .util import pythonic
from .exceptions import TableError, QueryError, PutError, DeleteError, UpdateError, GetError, ScanError
from ..types import HASH, RANGE
from pynamodb.constants import (
    RETURN_CONSUMED_CAPACITY_VALUES, RETURN_ITEM_COLL_METRICS_VALUES, COMPARISON_OPERATOR_VALUES,
    RETURN_ITEM_COLL_METRICS, RETURN_CONSUMED_CAPACITY, RETURN_VALUES_VALUES, ATTR_UPDATE_ACTIONS,
    COMPARISON_OPERATOR, EXCLUSIVE_START_KEY, SCAN_INDEX_FORWARD, SCAN_FILTER_VALUES, ATTR_DEFINITIONS,
    BATCH_WRITE_ITEM, CONSISTENT_READ, ATTR_VALUE_LIST, DESCRIBE_TABLE, DEFAULT_REGION, KEY_CONDITIONS,
    BATCH_GET_ITEM, DELETE_REQUEST, SELECT_VALUES, RETURN_VALUES, REQUEST_ITEMS, ATTR_UPDATES,
    ATTRS_TO_GET, SERVICE_NAME, DELETE_ITEM, PUT_REQUEST, UPDATE_ITEM, SCAN_FILTER, TABLE_NAME,
    INDEX_NAME, KEY_SCHEMA, ATTR_NAME, ATTR_TYPE, TABLE_KEY, EXPECTED, KEY_TYPE, GET_ITEM, UPDATE,
    PUT_ITEM, HTTP_OK, SELECT, ACTION, EXISTS, VALUE, LIMIT, QUERY, SCAN, ITEM, LOCAL_SECONDARY_INDEXES,
    KEYS, KEY, EQ, SEGMENT, TOTAL_SEGMENTS, CREATE_TABLE, PROVISIONED_THROUGHPUT, READ_CAPACITY_UNITS,
    WRITE_CAPACITY_UNITS, GLOBAL_SECONDARY_INDEXES, PROJECTION, EXCLUSIVE_START_TABLE_NAME,
    DELETE_TABLE, UPDATE_TABLE, LIST_TABLES, GLOBAL_SECONDARY_INDEX_UPDATES, HTTP_BAD_REQUEST)


class MetaTable(object):
    """
    A pythonic wrapper around table metadata
    """
    def __init__(self, data):
        self.data = data
        self._range_keyname = None
        self._hash_keyname = None

    def __repr__(self):
        if self.data:
            return six.u("MetaTable<{0}>".format(self.data.get(TABLE_NAME)))

    @property
    def range_keyname(self):
        """
        Returns the name of this table's range key
        """
        if self._range_keyname is None:
            for attr in self.data.get(KEY_SCHEMA):
                if attr.get(KEY_TYPE) == RANGE:
                    self._range_keyname = attr.get(ATTR_NAME)
        return self._range_keyname

    @property
    def hash_keyname(self):
        """
        Returns the name of this table's hash key
        """
        if self._hash_keyname is None:
            for attr in self.data.get(KEY_SCHEMA):
                if attr.get(KEY_TYPE) == HASH:
                    self._hash_keyname = attr.get(ATTR_NAME)
                    break
        return self._hash_keyname

    def get_item_attribute_map(self, attributes, item_key=ITEM, pythonic_key=True):
        """
        Builds up a dynamodb compatible AttributeValue map
        """
        if pythonic_key:
            item_key = pythonic(item_key)
        attr_map = {
            item_key: {}
        }
        for key, value in attributes.items():
            # In this case, the user provided a mapping
            # {'key': {'S': 'value'}}
            if isinstance(value, dict):
                attr_map[item_key][key] = value
            else:
                attr_map[item_key][key] = {
                    self.get_attribute_type(key): value
                }
        return attr_map

    def get_attribute_type(self, attribute_name):
        """
        Returns the proper attribute type for a given attribute name
        """
        for attr in self.data.get(ATTR_DEFINITIONS):
            if attr.get(ATTR_NAME) == attribute_name:
                return attr.get(ATTR_TYPE)
        attr_names = [attr.get(ATTR_NAME) for attr in self.data.get(ATTR_DEFINITIONS)]
        raise ValueError("No attribute {0} in {1}".format(attribute_name, attr_names))

    def get_identifier_map(self, hash_key, range_key=None, key=KEY):
        """
        Builds the identifier map that is common to several operations
        """
        kwargs = {
            pythonic(key): {
                self.hash_keyname: {
                    self.get_attribute_type(self.hash_keyname): hash_key
                }
            }
        }
        if range_key:
            kwargs[pythonic(key)][self.range_keyname] = {
                self.get_attribute_type(self.range_keyname): range_key
            }
        return kwargs

    def get_expected_map(self, expected):
        """
        Builds the expected map that is common to several operations
        """
        kwargs = {pythonic(EXPECTED): {}}
        for key, condition in expected.items():
            if EXISTS in condition:
                kwargs[pythonic(EXPECTED)][key] = {
                    EXISTS: condition.get(EXISTS)
                }
            elif VALUE in condition:
                kwargs[pythonic(EXPECTED)][key] = {
                    VALUE: {
                        self.get_attribute_type(key): condition.get(VALUE)
                    }
                }
        return kwargs

    def get_exclusive_start_key_map(self, exclusive_start_key):
        """
        Builds the exclusive start key attribute map
        """
        return {
            pythonic(EXCLUSIVE_START_KEY): {
                self.hash_keyname: {
                    self.get_attribute_type(self.hash_keyname): exclusive_start_key
                }
            }
        }


class Connection(object):
    """
    A higher level abstraction over botocore
    """
    def __init__(self, region=None, host=None):
        self._endpoint = None
        self._session = None
        self._service = None
        self._tables = {}
        self.host = host
        if region:
            self.region = region
        else:
            self.region = DEFAULT_REGION

    def __repr__(self):
        return six.u("Connection<{0}>".format(self.endpoint.host))

    @property
    def session(self):
        """
        Returns a valid botocore session
        """
        if self._session is None:
            self._session = get_session()
        return self._session

    @property
    def service(self):
        """
        Returns a reference to the dynamodb service
        """
        if self._service is None:
            self._service = self.session.get_service(SERVICE_NAME)
        return self._service

    @property
    def endpoint(self):
        """
        Returns an endpoint connection to `self.region`
        """
        if self._endpoint is None:
            if self.host:
                self._endpoint = self.service.get_endpoint(self.region, endpoint_url=self.host)
            else:
                self._endpoint = self.service.get_endpoint(self.region)
        return self._endpoint

    def get_meta_table(self, table_name, refresh=False):
        """
        Returns a MetaTable
        """
        if table_name not in self._tables or refresh:
            operation_kwargs = {
                pythonic(TABLE_NAME): table_name
            }
            response, data = self.service.get_operation(DESCRIBE_TABLE).call(self.endpoint, **operation_kwargs)
            if not response.ok:
                if response.status_code == HTTP_BAD_REQUEST:
                    return None
                else:
                    raise TableError("Unable to describe table: {0}".format(response.content))
            self._tables[table_name] = MetaTable(data.get(TABLE_KEY))
        return self._tables[table_name]

    def create_table(self,
                     table_name,
                     attribute_definitions=None,
                     key_schema=None,
                     read_capacity_units=None,
                     write_capacity_units=None,
                     global_secondary_indexes=None,
                     local_secondary_indexes=None,
                     ):
        """
        Performs the CreateTable operation
        """
        operation = self.service.get_operation(CREATE_TABLE)
        operation_kwargs = {
            pythonic(TABLE_NAME): table_name,
            pythonic(PROVISIONED_THROUGHPUT): {
                READ_CAPACITY_UNITS: read_capacity_units,
                WRITE_CAPACITY_UNITS: write_capacity_units
            }
        }
        attrs_list = []
        if attribute_definitions is None:
            raise ValueError("attribute_definitions argument is required")
        for attr in attribute_definitions:
            attrs_list.append({
                ATTR_NAME: attr.get(pythonic(ATTR_NAME)),
                ATTR_TYPE: attr.get(pythonic(ATTR_TYPE))
            })
        operation_kwargs[pythonic(ATTR_DEFINITIONS)] = attrs_list

        if global_secondary_indexes:
            global_secondary_indexes_list = []
            for index in global_secondary_indexes:
                global_secondary_indexes_list.append({
                    INDEX_NAME: index.get(pythonic(INDEX_NAME)),
                    KEY_SCHEMA: index.get(pythonic(KEY_SCHEMA)),
                    PROJECTION: index.get(pythonic(PROJECTION)),
                    PROVISIONED_THROUGHPUT: index.get(pythonic(PROVISIONED_THROUGHPUT))
                })
            operation_kwargs[pythonic(GLOBAL_SECONDARY_INDEXES)] = global_secondary_indexes_list

        if key_schema is None:
            raise ValueError("key_schema is required")
        key_schema_list = []
        for item in key_schema:
            key_schema_list.append({
                ATTR_NAME: item.get(pythonic(ATTR_NAME)),
                KEY_TYPE: str(item.get(pythonic(KEY_TYPE))).upper()
            })
        operation_kwargs[pythonic(KEY_SCHEMA)] = sorted(key_schema_list, key=lambda x: x.get(KEY_TYPE))

        local_secondary_indexes_list = []
        if local_secondary_indexes:
            for index in local_secondary_indexes:
                local_secondary_indexes_list.append({
                    INDEX_NAME: index.get(pythonic(INDEX_NAME)),
                    KEY_SCHEMA: index.get(pythonic(KEY_SCHEMA)),
                    PROJECTION: index.get(pythonic(PROJECTION)),
                })
            operation_kwargs[pythonic(LOCAL_SECONDARY_INDEXES)] = local_secondary_indexes_list
        response, data = operation.call(self.endpoint, **operation_kwargs)
        if response.status_code != HTTP_OK:
            raise TableError("Failed to create table: {0}".format(response.content))
        return data

    def delete_table(self, table_name):
        """
        Performs the DeleteTable operation
        """
        operation = self.service.get_operation(DELETE_TABLE)
        operation_kwargs = {
            pythonic(TABLE_NAME): table_name
        }
        response, data = operation.call(self.endpoint, **operation_kwargs)
        if response.status_code != HTTP_OK:
            raise TableError("Failed to delete table: {0}".format(response.content))

    def update_table(self,
                     table_name,
                     read_capacity_units=None,
                     write_capacity_units=None,
                     global_secondary_index_updates=None):
        """
        Performs the UpdateTable operation
        """
        operation = self.service.get_operation(UPDATE_TABLE)
        operation_kwargs = {
            pythonic(TABLE_NAME): table_name
        }
        if read_capacity_units and not write_capacity_units or write_capacity_units and not read_capacity_units:
            raise ValueError("read_capacity_units and write_capacity_units are required together")
        if read_capacity_units and write_capacity_units:
            operation_kwargs[pythonic(PROVISIONED_THROUGHPUT)] = {
                READ_CAPACITY_UNITS: read_capacity_units,
                WRITE_CAPACITY_UNITS: write_capacity_units
            }
        if global_secondary_index_updates:
            global_secondary_indexes_list = []
            for index in global_secondary_index_updates:
                global_secondary_indexes_list.append({
                    UPDATE: {
                        INDEX_NAME: index.get(pythonic(INDEX_NAME)),
                        PROVISIONED_THROUGHPUT: {
                            READ_CAPACITY_UNITS: index.get(pythonic(READ_CAPACITY_UNITS)),
                            WRITE_CAPACITY_UNITS: index.get(pythonic(WRITE_CAPACITY_UNITS))
                        }
                    }
                })
            operation_kwargs[pythonic(GLOBAL_SECONDARY_INDEX_UPDATES)] = global_secondary_indexes_list
        response, data = operation.call(self.endpoint, **operation_kwargs)
        if not response.ok:
            raise TableError("Failed to update table: {0}".format(response.content))

    def list_tables(self, exclusive_start_table_name=None, limit=None):
        """
        Performs the ListTables operation
        """
        operation = self.service.get_operation(LIST_TABLES)
        operation_kwargs = {}
        if exclusive_start_table_name:
            operation_kwargs.update({
                pythonic(EXCLUSIVE_START_TABLE_NAME): exclusive_start_table_name
            })
        if limit:
            operation_kwargs.update({
                pythonic(LIMIT): limit
            })
        response, data = operation.call(self.endpoint, **operation_kwargs)
        if not response.ok:
            raise TableError("Unable to list tables: {0}".format(response.content))
        return data

    def describe_table(self, table_name):
        """
        Performs the DescribeTable operation
        """
        tbl = self.get_meta_table(table_name, refresh=True)
        if tbl:
            return tbl.data
        else:
            return None

    def get_item_attribute_map(self, table_name, attributes, item_key=ITEM, pythonic_key=True):
        """
        Builds up a dynamodb compatible AttributeValue map
        """
        return self.get_meta_table(table_name).get_item_attribute_map(
            attributes,
            item_key=item_key,
            pythonic_key=pythonic_key)

    def get_attribute_type(self, table_name, attribute_name):
        """
        Returns the proper attribute type for a given attribute name
        """
        return self.get_meta_table(table_name).get_attribute_type(attribute_name)

    def get_identifier_map(self, table_name, hash_key, range_key=None, key=KEY):
        """
        Builds the identifier map that is common to several operations
        """
        return self.get_meta_table(table_name).get_identifier_map(hash_key, range_key=range_key, key=key)

    def get_expected_map(self, table_name, expected):
        """
        Builds the expected map that is common to several operations
        """
        return self.get_meta_table(table_name).get_expected_map(expected)

    def get_consumed_capacity_map(self, return_consumed_capacity):
        """
        Builds the consumed capacity map that is common to several operations
        """
        if return_consumed_capacity.upper() not in RETURN_CONSUMED_CAPACITY_VALUES:
            raise ValueError("{0} must be one of {1}".format(RETURN_ITEM_COLL_METRICS, RETURN_CONSUMED_CAPACITY_VALUES))
        return {
            pythonic(RETURN_CONSUMED_CAPACITY): str(return_consumed_capacity).upper()
        }

    def get_return_values_map(self, return_values):
        """
        Builds the return values map that is common to several operations
        """
        if return_values.upper() not in RETURN_VALUES_VALUES:
            raise ValueError("{0} must be one of {1}".format(RETURN_VALUES, RETURN_VALUES_VALUES))
        return {
            pythonic(RETURN_VALUES): str(return_values).upper()
        }

    def get_item_collection_map(self, return_item_collection_metrics):
        """
        Builds the item collection map
        """
        if return_item_collection_metrics.upper() not in RETURN_ITEM_COLL_METRICS_VALUES:
            raise ValueError("{0} must be one of {1}".format(RETURN_ITEM_COLL_METRICS, RETURN_ITEM_COLL_METRICS_VALUES))
        return {
            pythonic(RETURN_ITEM_COLL_METRICS): str(return_item_collection_metrics).upper()
        }

    def get_exclusive_start_key_map(self, table_name, exclusive_start_key):
        """
        Builds the exclusive start key attribute map
        """
        return self.get_meta_table(table_name).get_exclusive_start_key_map(exclusive_start_key)

    def delete_item(self,
                    table_name,
                    hash_key,
                    range_key=None,
                    expected=None,
                    return_values=None,
                    return_consumed_capacity=None,
                    return_item_collection_metrics=None):
        """
        Performs the DeleteItem operation and returns the result
        """
        operation = self.service.get_operation(DELETE_ITEM)
        operation_kwargs = {pythonic(TABLE_NAME): table_name}
        operation_kwargs.update(self.get_identifier_map(table_name, hash_key, range_key))

        if expected:
            operation_kwargs.update(self.get_expected_map(table_name, expected))
        if return_values:
            operation_kwargs.update(self.get_return_values_map(return_values))
        if return_consumed_capacity:
            operation_kwargs.update(self.get_consumed_capacity_map(return_consumed_capacity))
        if return_item_collection_metrics:
            operation_kwargs.update(self.get_item_collection_map(return_item_collection_metrics))
        response, data = operation.call(self.endpoint, **operation_kwargs)

        if not response.ok:
            raise DeleteError("Failed to delete item: {0}".format(response.content))
        return data

    def update_item(self,
                    table_name,
                    hash_key,
                    range_key=None,
                    attribute_updates=None,
                    expected=None,
                    return_consumed_capacity=None,
                    return_item_collection_metrics=None,
                    return_values=None
                    ):
        """
        Performs the UpdateItem operation
        """
        operation = self.service.get_operation(UPDATE_ITEM)
        operation_kwargs = {pythonic(TABLE_NAME): table_name}
        operation_kwargs.update(self.get_identifier_map(table_name, hash_key, range_key))
        if expected:
            operation_kwargs.update(self.get_expected_map(table_name, expected))
        if return_consumed_capacity:
                operation_kwargs.update(self.get_consumed_capacity_map(return_consumed_capacity))
        if return_item_collection_metrics:
            operation_kwargs.update(self.get_item_collection_map(return_item_collection_metrics))
        if return_values:
            operation_kwargs.update(self.get_return_values_map(return_values))
        if not attribute_updates:
            raise ValueError("{0} cannot be empty".format(ATTR_UPDATES))
        # {"path": {"Action": "PUT", Value: "Foo"}}

        operation_kwargs[pythonic(ATTR_UPDATES)] = {}
        for key, update in attribute_updates.items():
            attr_type = self.get_attribute_type(table_name, key)
            action = update.get(ACTION)
            if action not in ATTR_UPDATE_ACTIONS:
                raise ValueError("{0} must be one of {1}".format(ACTION, ATTR_UPDATE_ACTIONS))
            operation_kwargs[pythonic(ATTR_UPDATES)][key] = {
                ACTION: action,
                VALUE: {
                    attr_type: update.get(VALUE)
                }
            }
        response, data = operation.call(self.endpoint, **operation_kwargs)

        if not response.ok:
            raise UpdateError("Failed to update item: {0}".format(response.content))
        return data

    def put_item(self,
                 table_name,
                 hash_key,
                 range_key=None,
                 attributes=None,
                 expected=None,
                 return_values=None,
                 return_consumed_capacity=None,
                 return_item_collection_metrics=None):
        """
        Performs the PutItem operation and returns the result
        """
        operation = self.service.get_operation(PUT_ITEM)
        operation_kwargs = {pythonic(TABLE_NAME): table_name}
        operation_kwargs.update(self.get_identifier_map(table_name, hash_key, range_key, key=ITEM))
        if attributes:
            attrs = self.get_item_attribute_map(table_name, attributes)
            operation_kwargs[pythonic(ITEM)].update(attrs[pythonic(ITEM)])
        if return_consumed_capacity:
            operation_kwargs.update(self.get_consumed_capacity_map(return_consumed_capacity))
        if return_item_collection_metrics:
            operation_kwargs.update(self.get_item_collection_map(return_item_collection_metrics))
        if return_values:
            operation_kwargs.update(self.get_return_values_map(return_values))
        if expected:
            operation_kwargs.update(self.get_expected_map(table_name, expected))

        response, data = operation.call(self.endpoint, **operation_kwargs)
        if not response.ok:
            raise PutError("Failed to put item: {0}".format(response.content))
        return data

    def batch_write_item(self,
                         table_name,
                         put_items=None,
                         delete_items=None,
                         return_consumed_capacity=None,
                         return_item_collection_metrics=None):
        """
        Performs the batch_write_item operation
        """
        if put_items is None and delete_items is None:
            raise ValueError("Either put_items or delete_items must be specified")
        operation = self.service.get_operation(BATCH_WRITE_ITEM)
        operation_kwargs = {
            pythonic(REQUEST_ITEMS): {
                table_name: []
            }
        }
        if return_consumed_capacity:
            operation_kwargs.update(self.get_consumed_capacity_map(return_consumed_capacity))
        if return_item_collection_metrics:
            operation_kwargs.update(self.get_item_collection_map(return_item_collection_metrics))
        put_items_list = []
        if put_items:
            for item in put_items:
                put_items_list.append({
                    PUT_REQUEST: self.get_item_attribute_map(table_name, item, pythonic_key=False)
                })
        delete_items_list = []
        if delete_items:
            for item in delete_items:
                delete_items_list.append({
                    DELETE_REQUEST: self.get_item_attribute_map(table_name, item, item_key=KEY, pythonic_key=False)
                })
        operation_kwargs[pythonic(REQUEST_ITEMS)][table_name] = delete_items_list + put_items_list
        response, data = operation.call(self.endpoint, **operation_kwargs)
        if not response.ok:
            raise PutError("Failed to batch write items: {0}".format(response.content))
        return data

    def batch_get_item(self,
                       table_name,
                       keys,
                       consistent_read=None,
                       return_consumed_capacity=None,
                       attributes_to_get=None):
        """
        Performs the batch get item operation
        """
        operation = self.service.get_operation(BATCH_GET_ITEM)
        operation_kwargs = {
            pythonic(REQUEST_ITEMS): {
                table_name: {}
            }
        }

        args_map = {}
        if consistent_read:
            args_map[pythonic(CONSISTENT_READ)] = consistent_read
        if return_consumed_capacity:
            operation_kwargs.update(self.get_consumed_capacity_map(return_consumed_capacity))
        if attributes_to_get is not None:
            args_map[pythonic(ATTRS_TO_GET)] = attributes_to_get
        operation_kwargs[pythonic(REQUEST_ITEMS)][table_name].update(args_map)

        keys_map = {KEYS: []}
        for key in keys:
            keys_map[KEYS].append(
                self.get_item_attribute_map(table_name, key)[pythonic(ITEM)]
            )
        operation_kwargs[pythonic(REQUEST_ITEMS)][table_name].update(keys_map)
        response, data = operation.call(self.endpoint, **operation_kwargs)
        if not response.ok:
            raise GetError("Failed to batch get items: {0}".format(response.content))
        return data

    def get_item(self,
                 table_name,
                 hash_key,
                 range_key=None,
                 consistent_read=False,
                 attributes_to_get=None):
        """
        Performs the GetItem operation and returns the result
        """
        operation = self.service.get_operation(GET_ITEM)
        operation_kwargs = {}
        if attributes_to_get is not None:
            operation_kwargs[pythonic(ATTRS_TO_GET)] = attributes_to_get
        operation_kwargs[pythonic(CONSISTENT_READ)] = consistent_read
        operation_kwargs[pythonic(TABLE_NAME)] = table_name
        operation_kwargs.update(self.get_identifier_map(table_name, hash_key, range_key))
        response, data = operation.call(self.endpoint, **operation_kwargs)
        if not response.ok:
            raise GetError("Failed to get item: {0}".format(response.content))
        return data

    def scan(self,
             table_name,
             attributes_to_get=None,
             limit=None,
             scan_filter=None,
             return_consumed_capacity=None,
             exclusive_start_key=None,
             segment=None,
             total_segments=None):
        """
        Performs the scan operation
        """
        operation = self.service.get_operation(SCAN)
        operation_kwargs = {pythonic(TABLE_NAME): table_name}
        if attributes_to_get is not None:
            operation_kwargs[pythonic(ATTRS_TO_GET)] = attributes_to_get
        if limit:
            operation_kwargs[pythonic(LIMIT)] = limit
        if return_consumed_capacity:
            operation_kwargs.update(self.get_consumed_capacity_map(return_consumed_capacity))
        if exclusive_start_key:
            operation_kwargs.update(self.get_exclusive_start_key_map(table_name, exclusive_start_key))
        if segment:
            operation_kwargs[pythonic(SEGMENT)] = segment
        if total_segments:
            operation_kwargs[pythonic(TOTAL_SEGMENTS)] = total_segments
        if scan_filter:
            operation_kwargs[pythonic(SCAN_FILTER)] = {}
            for key, condition in scan_filter.items():
                attr_type = self.get_attribute_type(table_name, key)
                operator = condition.get(COMPARISON_OPERATOR)
                if operator not in SCAN_FILTER_VALUES:
                    raise ValueError("{0} must be one of {1}".format(COMPARISON_OPERATOR, SCAN_FILTER_VALUES))
                operation_kwargs[pythonic(SCAN_FILTER)][key] = {
                    ATTR_VALUE_LIST: [{attr_type: value for value in condition.get(ATTR_VALUE_LIST)}],
                    COMPARISON_OPERATOR: operator
                }
        response, data = operation.call(self.endpoint, **operation_kwargs)
        if not response.ok:
            raise ScanError("Failed to scan table: {0}".format(response.content))
        return data

    def query(self,
              table_name,
              hash_key,
              attributes_to_get=None,
              consistent_read=False,
              exclusive_start_key=None,
              index_name=None,
              key_conditions=None,
              limit=None,
              return_consumed_capacity=None,
              scan_index_forward=None,
              select=None
              ):
        """
        Performs the Query operation and returns the result
        """
        operation = self.service.get_operation(QUERY)
        operation_kwargs = {pythonic(TABLE_NAME): table_name}
        if attributes_to_get:
            operation_kwargs[pythonic(ATTRS_TO_GET)] = attributes_to_get
        if consistent_read:
            operation_kwargs[pythonic(CONSISTENT_READ)] = True
        if exclusive_start_key:
            operation_kwargs.update(self.get_exclusive_start_key_map(table_name, exclusive_start_key))
        if index_name:
            operation_kwargs[pythonic(INDEX_NAME)] = index_name
        if limit:
            operation_kwargs[pythonic(LIMIT)] = limit
        if return_consumed_capacity:
            operation_kwargs.update(self.get_consumed_capacity_map(return_consumed_capacity))
        if select:
            if select.upper() not in SELECT_VALUES:
                raise ValueError("{0} must be one of {1}".format(SELECT, SELECT_VALUES))
            operation_kwargs[pythonic(SELECT)] = str(select).upper()
        if scan_index_forward is not None:
            operation_kwargs[pythonic(SCAN_INDEX_FORWARD)] = scan_index_forward
        hash_keyname = self.get_meta_table(table_name).hash_keyname
        operation_kwargs[pythonic(KEY_CONDITIONS)] = {
            hash_keyname: {
                ATTR_VALUE_LIST: [{
                    self.get_attribute_type(table_name, hash_keyname): hash_key,
                }],
                COMPARISON_OPERATOR: EQ
            },
        }
        # key_conditions = {'key': {'ComparisonOperator': 'EQ', 'AttributeValueList': ['value']}
        if key_conditions:
            for key, condition in key_conditions.items():
                attr_type = self.get_attribute_type(table_name, key)
                operator = condition.get(COMPARISON_OPERATOR)
                if operator not in COMPARISON_OPERATOR_VALUES:
                    raise ValueError("{0} must be one of {1}".format(COMPARISON_OPERATOR, COMPARISON_OPERATOR_VALUES))
                operation_kwargs[pythonic(KEY_CONDITIONS)][key] = {
                    ATTR_VALUE_LIST: [{attr_type: value for value in condition.get(ATTR_VALUE_LIST)}],
                    COMPARISON_OPERATOR: operator
                }

        response, data = operation.call(self.endpoint, **operation_kwargs)
        if not response.ok:
            raise QueryError("Failed to query items: {0}".format(response.content))
        return data