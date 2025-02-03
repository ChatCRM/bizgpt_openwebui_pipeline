"""
title: Haystack Pipeline
author: open-webui
date: 2024-05-30
version: 1.0
license: MIT
description: A pipeline for retrieving relevant information from a knowledge base using the Haystack library.
requirements: haystack-ai, datasets>=2.6.1, sentence-transformers>=2.2.0
"""
import os
import math
import requests

from typing import List, Union, Generator, Iterator, Optional, Dict
from schemas import OpenAIChatMessage

import openai
from dataclasses import dataclass

from elasticsearch import Elasticsearch
from typing import Dict, List, Optional, Any
import json
import logging
from urllib3.exceptions import InsecureRequestWarning
import urllib3
# Suppress insecure HTTPS warnings
urllib3.disable_warnings(InsecureRequestWarning)

from pydantic import BaseModel
from supabase import create_client, Client


@dataclass
class KeywordVariation:
    original: str
    zwnj_variations: List[str]
    synonym: str


class PersianKeywordExtractor:
    def __init__(self, api_key: str, question:str):
        self.client = openai.OpenAI(api_key=api_key)
        self.ZWNJ = '\u200c'
        self.rewrite_question = ""
        self.question = question

    def _alternative_questions(self) -> list:
        """Rewrite the input text with legal focus using GPT-4 and return results as a list."""
        prompt = f"""
            As a legal search query optimizer, process the following input to create a list for Elasticsearch:
        1. First item - Original question corrected for spelling/grammar: Fix typos and literal mistake while strictly maintaining original legal intent.
        and if abbreviations are used, expand them.
        
        2. Subsequent items - Generate 3-5 alternative phrasings that:
           - Use only legal synonyms
           - Preserve the exact legal meaning and scope of original query
           - if you cannot find to create any alternative, just skip
        
        Prioritize these elements in order:
        1. Meaning preservation (exact legal context)
        2. Search-friendly keyword combinations
        3. you must not change the original question in any way
        4. Elasticsearch tokenization considerations
        5. Do not add order numbers for you result, jus simple text for each item
        
        Format each list item as simple list item: [concise query terms]
        
            {self.question}
        """
        
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert legal assistant specializing in Persian legal terminology."},
                {"role": "user", "content": prompt}
            ]
        )
        
        # Extract the content from the response
        content = response.choices[0].message.content
        
        # Split the content into lines and remove empty lines or irrelevant formatting
        items = [line.strip() for line in content.split("\n") if line.strip()]
        
        return items


    
    def _rewrite_legal_text(self, text: str) -> str:
        """Rewrite the input text with legal focus using GPT-4."""
        prompt = f"""
        As a legal assistant, rewrite the following text to emphasize legal aspects and terminology,
        maintaining the same meaning but using more formal legal language:

        {text}
        """
        
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert legal assistant specializing in Persian legal terminology."},
                {"role": "user", "content": prompt}
            ]
        )
        
        return response.choices[0].message.content

    def extract_keywords(self, text: str) -> List[KeywordVariation]:
        """Extract keywords and their variations from Persian text."""
        # First, rewrite the text with legal focus
        legal_text = self._rewrite_legal_text(text)

        self.rewrite_question = legal_text
        
        # Then get base keywords from the legal version
        keywords = self._get_base_keywords(legal_text)
        
        # Generate variations for each keyword
        keyword_variations = []
        for keyword in keywords:
            variations = self._generate_variations(keyword)
            keyword_variations.append(variations)
        
        return keyword_variations

    def _get_base_keywords(self, text: str) -> List[str]:
        """Use GPT-4 to extract main keywords from text."""
        prompt = f"""
        You are a legal assistant.
        Extract important keywords from the following Persian legal text that can be useful for querying Elasticsearch. 
        Focus on technical and legal terms.
        Text: {text}
        
        Return only the keywords as a JSON array.
        """
        
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a Persian legal expert."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        keywords = json.loads(response.choices[0].message.content)["keywords"]
        return keywords


    def _llm_search(self, system_content:str, user_question):
        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_question}
            ]
        )
        return response
        
    
    def _generate_variations(self, keyword: str) -> KeywordVariation:
        """Generate simplified variations for a given keyword."""
        prompt = f"""
        For the Persian legal keyword "{keyword}", provide:
        1. All possible ZWNJ variations
        2. One common legal synonym
        
        Return as a JSON object with these keys:
        - zwnj_variations
        - synonym
        """
        
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a Persian legal expert."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        variations = json.loads(response.choices[0].message.content)
        
        return KeywordVariation(
            original=keyword,
            zwnj_variations=variations["zwnj_variations"],
            synonym=variations["synonym"]
        )


    def generate_elasticsearch_query_with_embedding_only(self,embedding_vector = None,num_candidates = 507, semantic_weight=0.6,keyword_weight= 0.3):
        items = self._alternative_questions()
        should_clauses = []
        if embedding_vector:
            embed_match = {
                "knn": {
                    "field": "embedding",
                    "query_vector": embedding_vector,
                    "k": 5,
                    "num_candidates": num_candidates,
                    "boost": semantic_weight
                }
            }
            should_clauses.append(embed_match)

        
        # Construct the complete Elasticsearch query
        es_query = {
            "_source": ["id_ghavanin", "title", "content", "metadata"],
            "query": {
                "bool": {
                    "should": should_clauses,
                    "must_not": [
                        {
                            "wildcard": {
                                "metadata.latest_status": "*منسوخ*"
                            }
                        }
                    ],
                    "minimum_should_match": 1
                }
            },
            "sort": [
                {
                    "metadata.approval_date.gregorian": {
                        "order": "desc",
                        "missing": "_last",
                        "unmapped_type": "date"
                    }
                },
                "_score"
            ],
            "size" : 8,
            "highlight": {
                "fields": {
                    "title": {},
                    "content": {}
                }
            }
        }
        
        return es_query
    
    def generate_elasticsearch_query_with_synonyms(self,alt_questions = None, embedding_vector = None,num_candidates = 507, semantic_weight=0.5,keyword_weight= 0.3 ):
        if alt_questions:
            items = alt_questions
        else:
            items = self._alternative_questions()
        
        should_clauses = [
            {
                "multi_match": {
                    "query": item,
                    "fields": ["content", "title"],
                    "analyzer": "persian",
                    # "minimum_should_match": "30%"
                }
            } for item in items
        ]

        if embedding_vector:
            embed_match = {
                "knn": {
                    "field": "embedding",
                    "query_vector": embedding_vector,
                    "k": 5,
                    "num_candidates": num_candidates,
                    "boost": semantic_weight
                }
            }
            should_clauses.append(embed_match)

        
        # Construct the complete Elasticsearch query
        es_query = {
            "_source": ["id_ghavanin", "title", "content", "metadata"],
            "min_score": 0.5,
            "query": {
                "bool": {
                    "should": should_clauses,
                    "must_not": [
                        {
                            "wildcard": {
                                "metadata.latest_status": "*منسوخ*"
                            }
                        }
                    ]
                }
            },
            "sort": [
                {
                    "metadata.approval_date.gregorian": {
                        "order": "desc",
                        "missing": "_last",
                        "unmapped_type": "date"
                    }
                },
                "_score"
            ],
            "size" : 15,
            "highlight": {
                "fields": {
                    "title": {},
                    "content": {}
                }
            }
        }
        
        return es_query

    
        
    def generate_elasticsearch_query(self, keyword_variations: List[KeywordVariation]) -> Dict:
        """Generate Elasticsearch query structure."""
        should_clauses = [
            {
                "multi_match": {
                    "query": self.rewrite_question,
                    "fields": ["content^3", "title^2"],
                    "type": "best_fields",
                    "operator": "OR",
                    "fuzziness": "AUTO"
                }
            }
        ]
        
        for kw in keyword_variations:
            # Combine variations for each keyword
            all_variations = (
                [kw.original] +
                kw.zwnj_variations +
                [kw.synonym]
            )
            
            # Remove duplicates while preserving order
            unique_variations = list(dict.fromkeys(all_variations))
            
            # Create multi_match query for each keyword group
            should_clauses.append({
                "multi_match": {
                    "query": " ".join(unique_variations),
                    "fields": ["content", "title"],
                    "type": "best_fields",
                    "operator": "OR",
                    "fuzziness": "AUTO"
                }
            })

        # Construct the complete Elasticsearch query
        es_query = {
            "_source": ["id_ghavanin", "title", "content", "metadata"],
            "min_score": 0.5,
            "query": {
                "bool": {
                    "should": should_clauses,
                    "must_not": [
                        {
                            "wildcard": {
                                "metadata.latest_status": "*منسوخ*"
                            }
                        }
                    ]
                }
            },
            "sort": [
                {
                    "metadata.approval_date": {
                        "order": "desc",
                        "missing": "_last",
                        "unmapped_type": "date"
                    }
                },
                "_score"
            ],
            "size" : 15,
            "highlight": {
                "fields": {
                    "title": {},
                    "content": {}
                }
            }
        }
        
        return es_query

    def get_embedding(self, text: str, model: str = "text-embedding-3-large") -> list:
        """
        Generate an embedding vector for the given text using OpenAI's embedding model.
        
        :param text: The input text to embed.
        :param model: The OpenAI embedding model to use (default: "text-embedding-ada-002").
        :return: A list representing the embedding vector.
        """
        response = self.client.embeddings.create(
            input=text,
            model=model
        )
        return response.data[0].embedding, response.usage.total_tokens



class ElasticsearchExecutor:
    def __init__(
            self, 
            hosts: List[str], 
            username: Optional[str] = None,
            password: Optional[str] = None,
            port: int = 9200,
            # use_ssl: bool = False,
            verify_certs: bool = False,
            scheme: str = "https"
        ):
        """
        Initialize Elasticsearch connection
        
        Args:
            hosts: List of Elasticsearch hosts
            username: Optional username for authentication
            password: Optional password for authentication
            port: Elasticsearch port (default: 9200)
            use_ssl: Whether to use SSL/TLS
            verify_certs: Whether to verify SSL certificates
            scheme: URL scheme (http or https)
        """
        try:

            # Configure connection
            es_config = {
                'hosts': hosts,
                'basic_auth': (username, password) if username and password else None,
                'verify_certs': False,
                'ssl_show_warn':False,
                # 'use_ssl': False,
                # 'timeout': 30,
                # 'retry_on_timeout': True,
                # 'max_retries': 3
            }

            # Test connection before creating client
            # self._test_connection(formatted_hosts[0], username, password)

            # Create Elasticsearch client
            self.es = Elasticsearch(**es_config)
            
            # Verify connection
            if not self.es.ping():
                raise ConnectionError("Could not connect to Elasticsearch")

        except Exception as e:
            logging.error(f"Failed to initialize Elasticsearch: {str(e)}")
            raise

    def _test_connection(self, host: str, username: Optional[str] = None, password: Optional[str] = None):
        """Test connection to Elasticsearch before creating client."""
        try:
            auth = (username, password) if username and password else None
            response = requests.get(
                f"{host}/_cluster/health",
                auth=auth,
                verify=False,
                timeout=5
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Connection test failed: {str(e)}")

    def get_index_size(self) -> int:
        try:
            res = self.es.count(index="ghavanin")
            return int(res['count'])
        except Exception as e:
            print(f"Failed to get index size: {str(e)}")
            raise

    def calculate_num_candidates(self, k: int, vector_dim: int = 3072) -> int:
        base = k * 10
        index_size = self.get_index_size()
        scale_factor = math.log(index_size / math.log(vector_dim))
        num_candidates = math.floor(min(max(base * scale_factor, 100), index_size // 2))
        # self.candidate_cache[(index_size, k, vector_dim)] = num_candidates
        return num_candidates
    
    def execute_query(self, query: Dict[str, Any], index: str = "ghavanin", size: int = 15) -> Dict[str, Any]:
        """Execute the query and return results"""
        try:
            # Verify connection before executing query
            if not self.es.ping():
                raise ConnectionError("Lost connection to Elasticsearch")

            # Add size parameter to query if not present
            if 'size' not in query:
                query['size'] = size

            # Execute search
            response = self.es.search(
                index=index,
                body=query,
                request_timeout=30
            )

            # Process results
            hits = response['hits']['hits']
            total_hits = response['hits']['total']['value']
            
            results = {
                'status': 'success',
                'total_hits': total_hits,
                'took': response['took'],
                'documents': [],
                'highlights': []
            }
            
            for hit in hits:
                doc = {
                    'id': hit['_id'],
                    'score': hit['_score'],
                    'source': hit['_source']
                }
                results['documents'].append(doc)
                
                if 'highlight' in hit:
                    results['highlights'].append({
                        'id': hit['_id'],
                        'highlights': hit['highlight']
                    })

            return results

        except Exception as e:
            error_response = {
                'status': 'error',
                'error': str(e),
                'error_type': type(e).__name__,
                'query': query
            }
            logging.error(f"Query execution failed: {str(e)}")
            return error_response




class Pipeline:
    class Valves(BaseModel):
        OPENAI_SECRET_KEY: str
        ELASTIC_SEARCH_USERNAME: str
        ELASTIC_SEARCH_PASSWORD: str
        ELASTIC_SEARCH_URL: str 

    def __init__(self):
        self.chat_id = None
        self.name = "مدل قوانین ایران"
        self.valves = self.Valves(
            **{
                "OPENAI_SECRET_KEY": os.getenv("OPENAI_SECRET_KEY", ""),
                "ELASTIC_SEARCH_USERNAME": os.getenv("ELASTIC_SEARCH_USERNAME", "elastic"),
                "ELASTIC_SEARCH_PASSWORD": os.getenv("ELASTIC_SEARCH_PASSWORD", ""),
                "ELASTIC_SEARCH_URL": os.getenv("ELASTIC_SEARCH_URL", ""),
            }
        )
        pass

    async def on_valves_updated(self):
        # This function is called when the valves are updated.
        # self.valves.VAKILGPT_API_URL = os.getenv("VAKILGPT_API_URL", "http://127.0.0.1:8000/question-answer/submit-stream-v2")
        # self.valves.SUPABASE_URL = os.getenv("SUPABASE_URL", ""),
        # self.valves.SUPABASE_KEY = os.getenv("SUPABASE_KEY", ""),
        pass
    
    async def on_startup(self):
        pass

    async def on_shutdown(self):
        # This function is called when the server is stopped.
        pass

    async def inlet(self, body: dict, user: Optional[dict] = None) -> dict:
      print(f"inlet:{__name__}")
      print(f"user: {user}")
      print(f"body: {body}")
      # Store the chat_id from body
      self.chat_id = body.get("chat_id")
      print(f"Stored chat_id: {self.chat_id}")

      return body

    @staticmethod
    def stream_sse_response(response):
      """
      Stream and parse Server-Sent Events (SSE) response in real-time.
      
      Args:
          response: The requests response object with stream=True
          
      Yields:
          str: The actual text content as it streams in
      """
      buffer = ""
      
      for line in response.iter_lines():
        if line:
            decoded_line = line.decode('utf-8')
            
            # Skip id, event, and retry lines
            if decoded_line.startswith(('id:', 'event:', 'retry:')):
                continue
                
            # Handle data lines
            if decoded_line.startswith('data: '):
                content = decoded_line[6:]  # Remove 'data: ' prefix
                
                # Skip empty data lines
                if not content.strip():
                    continue
                    
                # Handle complete event with JSON data
                if content.startswith('{'):
                    continue
                    # try:
                    #     import json
                    #     data = json.loads(content)
                    #     if isinstance(data, dict) and 'response' in data:
                    #         yield data['response']
                    #         buffer = ""
                    #         continue
                    # except json.JSONDecoder:
                    #     pass
                
                # Yield the actual content
                if content not in ('**', ':**') and  not content.startswith('{'):  # Skip markdown formatting markers
                    yield content

    def pipe(
        self, user_message: str, model_id: str, messages: List[dict], body: dict
    ) -> Union[str, Generator, Iterator]:
        # This is where you can add your custom RAG pipeline.
        # Typically, you would retrieve relevant information from your knowledge base and synthesize it to generate a response.

        print("Body is: ")
        print(body)
        print("Chat ID is: ")
        print(self.chat_id)

        print("All messages are: ")
        print(messages)
        
        es_url = self.valves.ELASTIC_SEARCH_URL
        es_username = self.valves.ELASTIC_SEARCH_USERNAME
        es_password = self.valves.ELASTIC_SEARCH_PASSWORD
        openai_key = self.valves.OPENAI_SECRET_KEY

        
        try:
            executor = ElasticsearchExecutor(es_url,es_username,es_password,9200)
            extractor = PersianKeywordExtractor(openai_key,user_message)
            new_questions = extractor._alternative_questions()
            embedding_vector, _= extractor.get_embedding(list(new_questions)[0])
            es_query = extractor.generate_elasticsearch_query_with_synonyms(alt_questions=new_questions,embedding_vector=embedding_vector)
            # Extract keywords and variations
            # keyword_variations = extractor.extract_keywords(user_message)
            # Generate Elasticsearch terms
            # es_query = extractor.generate_elasticsearch_query(keyword_variations)
            
            # Run executor
            results = executor.execute_query(es_query)

            docs = results['documents']
            system_prompt = """
                شما دستیار متخصص حقوق ایران هستید، لطفا تنها و تنها براساس اطللاعات داده شده به سوال کاربر پاسخ دهید
                دستور العمل پاسخ:
                ۱- تمامی مقرراتی که به سوال کاربر مربوط است را ذکر کن. وظیفه اصلی شما معرفی مراجعی است
                که برای پاسخ به سوال کاربر می‌تواند مورد استفاده قرار بگیرد.
                ۲- در صورتی که کاربر مجموعه ای یا لیستی از قوانین را درخواست کرد حتما تمامی منابع مربوطه را برگردان و به یک جواب اکتقا نکن
                ۴- هر منبعی که در اختیار داری و دارای تاریخ است جواب ها را براساس تاریخ از جدید به قدیم مرتب کن
                ۳- برای جواب نهایی لیست تمامی منابعی(مرجع ها) که استفاده کردی و به شما داده شده است را در انتها به صورت لیست 
                markdown
                و به صورت لینک وب سایت
                ذکر کن
                به یاد داشته باش که تنها و تنها باید از منابعی که در اختیارت گذاشته شده جواب دهی.
            """
            for doc in docs:
                date = doc['source']['metadata']['approval_date']['gregorian'] if 'metadata' in doc['source'] else ""
                law_type = doc['source']['metadata']['law_type'] if 'metadata' in doc['source'] else ""
                id_ghavanin = doc['source']['id_ghavanin']
                title = doc['source']['title']
                content = doc['source']['content']
                system_prompt += f"""
                ------
                نوع قانون: {law_type} 
                تاریخ: {date}
                عنوان: {title}
                متن: {content}
                مرجع: https://qavanin.ir/Law/TreeText/?IDS={id_ghavanin}
                    
                """
            res = extractor._llm_search(system_prompt,user_message)

            return res.choices[0].message.content

        except requests.exceptions.RequestException as e:
            print(f"An error occurred: {e}")
            return "خطایی در سیستم رخ داده است ."
