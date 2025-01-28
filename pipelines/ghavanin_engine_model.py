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
    def __init__(self, api_key: str):
        self.client = openai.OpenAI(api_key=api_key)
        self.ZWNJ = '\u200c'

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
            model="gpt-4o-mini",
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

    def generate_elasticsearch_query(self, keyword_variations: List[KeywordVariation]) -> Dict:
        """Generate Elasticsearch query structure."""
        should_clauses = []
        
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
                    "fields": ["content^3", "title^2"],
                    "type": "best_fields",
                    "operator": "OR",
                    "fuzziness": "AUTO"
                }
            })

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
            "size" : 5,
            "highlight": {
                "fields": {
                    "title": {},
                    "content": {}
                }
            }
        }
        
        return es_query


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

    def execute_query(self, query: Dict[str, Any], index: str = "ghavanin", size: int = 10) -> Dict[str, Any]:
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
            extractor = PersianKeywordExtractor(openai_key)
            # Extract keywords and variations
            keyword_variations = extractor.extract_keywords(user_message)
            # Generate Elasticsearch terms
            es_query = extractor.generate_elasticsearch_query(keyword_variations)
            # Initialize executor
            executor = ElasticsearchExecutor(es_url,es_username,es_password,9200)
            results = executor.execute_query(es_query)

            docs = results['documents']
            system_prompt = """
            شما دستیار متخصص حقوق ایران هستید، لطفا براساس اطللاعات داده شده به سوال کاربر پاسخ دهید
            برای جواب نهایی لیست تمامی منابعی(مرجع ها) که استفاده کردی را در انتها به صورت لیست 
            markdown
            به صورت لینک وب سایت
            ذکر کن
            """
            for doc in docs:
                date = doc['source']['metadata']['approval_date']['gregorian']
                law_type = doc['source']['metadata']['law_type']
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
