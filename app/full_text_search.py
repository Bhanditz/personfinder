#!/usr/bin/python2.7
# Copyright 2015 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import re

from google.appengine.api import search as appengine_search

import model
import script_variant

# The index name for full text search.
# This index contains person name and location.
PERSON_LOCATION_FULL_TEXT_INDEX_NAME = 'person_location_information'

def make_or_regexp(query_txt):
    """
    Creates compiled regular expression for OR search.
    Args:
        query_txt: Search query

    Returns:
        query_word | query_word | ...
    """
    query_words = query_txt.split(' ')
    regexp = '|'.join([re.escape(word) for word in query_words if word])
    return re.compile(regexp, re.I)

def enclose_in_double_quotes(query_txt):
    """
    Encloses each word in query_txt in double quotes.
    Args:
        query_txt: Search query

    Returns:
        '"query_word1" "query_word2" ...'
    """
    query_words = query_txt.split(' ')
    return '"' + '" "'.join([word for word in query_words if word]) + '"'

def search(repo, query_txt, max_results):
    """
    Searches person with index.
    Query_txt must match at least a part of person name.
    (It's not allowed to search only by location.)
    Args:
        repo: The name of repository
        query_txt: Search query
        max_results: The max number of results you want.(Maximum: 1000)

    Returns:
        - Array of <model.Person> in datastore
        - []: If query_txt doesn't contain a part of person name

    Raises:
        search.Error: An error occurred when the index name is unknown
                      or the query has syntax error.
    """
    #TODO: Sanitaize query_txt
    if not query_txt:
        return []

    # Remove double quotes so that we can safely apply enclose_in_double_quotes().

    romanized_query = script_variant.romanize_text(query_txt)
    query_txt = re.sub('"', '', romanized_query)

    person_location_index = appengine_search.Index(
        name=PERSON_LOCATION_FULL_TEXT_INDEX_NAME)
    options = appengine_search.QueryOptions(
        limit=max_results,
        returned_fields=['record_id',
                         'names_romanized_by_romanize_word_by_unidecode',
                         'names_romanized_by_romanize_japanese_name_by_name_dict'])

    # enclose_in_double_quotes is used for avoiding query_txt
    # which specifies index field name, contains special symbol, ...
    # (e.g., "repo: repository_name", "test: test", "test AND test").
    and_query = enclose_in_double_quotes(query_txt) + ' AND (repo: ' + repo + ')'
    person_location_index_results = person_location_index.search(
        appengine_search.Query(
            query_string=and_query, options=options))
    index_results = []
    regexp = make_or_regexp(query_txt)
    for document in person_location_index_results:
        names = ''
        romanized_jp_names = ''
        for field in document.fields:
            if field.name == 'names_romanized_by_romanize_word_by_unidecode':
                names = field.value
            if field.name == 'record_id':
                id = field.value
            if field.name == 'names_romanized_by_romanize_japanese_name_by_name_dict':
                romanized_jp_names = field.value

        if regexp.search(names) or regexp.search(romanized_jp_names):
            index_results.append(id)

    results = []
    for id in index_results:
        result = model.Person.get(repo, id, filter_expired=True)
        if result:
            results.append(result)
    return results


def create_full_name_without_space(given_names, family_names):
    """
    Creates full name without white space.
    Returns:
        if given_name and family_name: ('given_name + family_name',
                                        'family_name + given_name')
        else: None
    """
    if given_names and family_names:
        full_names = []
        for index1 in xrange(len(given_names)):
            given_name = given_names[index1]
            for index2 in xrange(len(family_names)):
                family_name = family_names[index2]
                full_names.append(
                    (given_name + family_name,
                    family_name + given_name))
        return full_names
    else:
        return None


def create_full_name_without_space_fields(romanize_method, given_name, family_name):
    """
    Creates fields with the full name without white spaces.
    Returns:
        fullname fields, romanized_name_list: (for check)
    """
    fields = []
    romanized_name_list = []
    romanized_given_name = romanize_method(given_name)
    romanized_family_name = romanize_method(family_name)
    romanize_method_name = romanize_method.__name__
    full_names = create_full_name_without_space(
        romanized_given_name, romanized_family_name)
    if full_names:
        for index in xrange(len(full_names)):
            full_name_given_family, full_name_family_given = full_names[index]
            fields.append(appengine_search.TextField(
                name='no_space_full_name_1_romanized_by_'+romanize_method_name+\
                     '_'+str(index),
                value=full_name_given_family))
            romanized_name_list.append(full_name_given_family)
            fields.append(appengine_search.TextField(
                name='no_space_full_name_2_romanized_by_'+romanize_method_name+\
                     '_'+str(index),
                value=full_name_family_given))
            romanized_name_list.append(full_name_family_given)
    return fields, romanized_name_list


def create_romanized_name_fields(romanize_method, **kwargs):
    """
    Creates romanized name fields (romanized by romanize_method)
    for full text search.
    """
    fields = []
    romanized_names_list = []
    romanize_method_name = romanize_method.__name__
    for field in kwargs:
        romanized_names = romanize_method(kwargs[field])
        if romanized_names:
            logging.info(romanized_names)
            for index in xrange(len(romanized_names)):
                romanized_name = romanized_names[index]
                if romanized_name:
                    fields.append(
                        appengine_search.TextField(
                            name=field+'_romanized_by_'+romanize_method_name+\
                                 '_'+str(index),
                            value=romanized_name))
            romanized_names_list.extend(romanized_names)

    full_name_fields, romanized_full_names = create_full_name_without_space_fields(
        romanize_method, kwargs['given_name'], kwargs['family_name'])
    fields.extend(full_name_fields)
    romanized_names_list.extend(romanized_full_names)

    names = ':'.join([name for name in romanized_names_list if name])
    fields.append(
        appengine_search.TextField(name='names_romanized_by_'+romanize_method_name,
                                   value=names))

    return fields


def create_romanized_location_fields(romanize_method, **kwargs):
    """
    Creates romanized location fields (romanized by romanize_method)
    for full text search.
    """
    fields = []
    romanize_method_name = romanize_method.__name__
    for field in kwargs:
        romanized_locations = romanize_method(kwargs[field])
        if romanized_locations:
            for index in xrange(len(romanized_locations)):
                romanized_location = romanized_locations[index]
                if romanized_location:
                    fields.append(
                        appengine_search.TextField(
                            name=field+'_romanized_by_'+romanize_method_name+\
                                 '_'+str(index),
                            value=romanized_location)
                    )
    return fields

def create_document(person):
    """
    Creates document for full text search.
    It should be called in add_record_to_index method.
    """
    fields = []

    # Add repo and record_id to fields
    repo = person.repo
    record_id = person.record_id
    doc_id = repo + ':' + record_id
    fields.append(appengine_search.TextField(name='repo', value=repo))
    fields.append(appengine_search.TextField(name='record_id', value=record_id))

    # Applies two methods because kanji is used in Chinese and Japanese,
    # and romanizing in chinese and japanese is different.
    romanize_name_methods = [script_variant.romanize_word_by_unidecode,
                             script_variant.romanize_japanese_name_by_name_dict]

    romanize_location_mathods = [script_variant.romanize_word_by_unidecode,
                                 script_variant.romanize_japanese_location]

    for romanize_method in romanize_name_methods:
        fields.extend(create_romanized_name_fields(
            romanize_method,
            given_name=person.given_name,
            family_name=person.family_name,
            full_name=person.full_name,
            alternate_names=person.alternate_names))

    for romanize_method in romanize_location_mathods:
        fields.extend(create_romanized_location_fields(
            romanize_method,
            home_street=person.home_street,
            home_city=person.home_city,
            home_state=person.home_state,
            home_postal_code=person.home_postal_code,
            home_neighborhood=person.home_neighborhood,
            home_country=person.home_country))

    return appengine_search.Document(doc_id=doc_id, fields=fields)


def add_record_to_index(person):
    """
    Adds person record to index.
    Raises:
        search.Error: An error occurred when the document could not be indexed
                      or the query has a syntax error.
    """
    person_location_index = appengine_search.Index(
        name=PERSON_LOCATION_FULL_TEXT_INDEX_NAME)
    person_location_index.put(create_document(person))


def delete_record_from_index(person):
    """
    Deletes person record from index.
    Args:
        person: Person who should be removed
    Raises:
        search.Error: An error occurred when the index name is unknown
                      or the query has a syntax error.
    """
    doc_id = person.repo + ':' + person.record_id
    person_location_index = appengine_search.Index(
        name=PERSON_LOCATION_FULL_TEXT_INDEX_NAME)
    person_location_index.delete(doc_id)
