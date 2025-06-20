from typing import Any, Dict, List, Optional, Union

from langchain.chat_models.base import BaseChatModel
from langchain.embeddings.base import Embeddings
from langchain_qdrant import FastEmbedSparse, QdrantVectorStore, RetrievalMode
from qdrant_client import QdrantClient
from qdrant_client.http.models import FieldCondition, Filter, MatchValue

from app.config.configuration_service import config_node_constants
from app.config.utils.named_constants.ai_models_named_constants import (
    AZURE_EMBEDDING_API_VERSION,
    DEFAULT_EMBEDDING_MODEL,
    AzureOpenAILLM,
    EmbeddingProvider,
    LLMProvider,
)
from app.config.utils.named_constants.arangodb_constants import (
    CollectionNames,
    Connectors,
    RecordTypes,
)
from app.core.embedding_service import (
    AzureEmbeddingConfig,
    CohereEmbeddingConfig,
    EmbeddingFactory,
    GeminiEmbeddingConfig,
    HuggingFaceEmbeddingConfig,
    OpenAICompatibleEmbeddingConfig,
    OpenAIEmbeddingConfig,
    SentenceTransformersEmbeddingConfig,
)
from app.core.llm_service import (
    AnthropicLLMConfig,
    AwsBedrockLLMConfig,
    AzureLLMConfig,
    GeminiLLMConfig,
    LLMFactory,
    OllamaConfig,
    OpenAICompatibleLLMConfig,
    OpenAILLMConfig,
)
from app.exceptions.embedding_exceptions import EmbeddingModelCreationError
from app.exceptions.fastapi_responses import Status
from app.exceptions.indexing_exceptions import IndexingError
from app.modules.retrieval.retrieval_arango import ArangoService
from app.utils.embeddings import get_default_embedding_model


class RetrievalService:
    def __init__(
        self,
        logger,
        config_service,
        collection_name: str,
        qdrant_client: QdrantClient,
    ) -> None:
        """
        Initialize the retrieval service with necessary configurations.

        Args:
            collection_name: Name of the Qdrant collection
            qdrant_api_key: API key for Qdrant
            qdrant_host: Qdrant server host URL
        """

        self.logger = logger
        self.config_service = config_service
        self.llm = None

        # Initialize sparse embeddings
        try:
            self.sparse_embeddings = FastEmbedSparse(model_name="Qdrant/BM25")
        except Exception as e:
            self.logger.error("Failed to initialize sparse embeddings: " + str(e))
            self.sparse_embeddings = None
            raise Exception(
                "Failed to initialize sparse embeddings: " + str(e),
            )
        self.qdrant_client = qdrant_client
        self.collection_name = collection_name
        self.logger.info(f"Retrieval service initialized with collection name: {self.collection_name}")
        self.vector_store = None

    async def get_llm_instance(self) -> Optional[BaseChatModel]:
        try:
            self.logger.info("Getting LLM")
            ai_models = await self.config_service.get_config(
                config_node_constants.AI_MODELS.value
            )
            llm_configs = ai_models["llm"]
            # For now, we'll use the first available provider that matches our supported types
            # We will add logic to choose a specific provider based on our needs
            llm_config = None

            for config in llm_configs:
                provider = config["provider"]
                if provider == LLMProvider.AZURE_OPENAI.value:
                    llm_config = AzureLLMConfig(
                        model=config["configuration"]["model"],
                        temperature=0.2,
                        api_key=config["configuration"]["apiKey"],
                        azure_endpoint=config["configuration"]["endpoint"],
                        azure_api_version=AzureOpenAILLM.AZURE_OPENAI_VERSION.value,
                        azure_deployment=config["configuration"]["deploymentName"],
                    )
                    break
                elif provider == LLMProvider.OPENAI.value:
                    llm_config = OpenAILLMConfig(
                        model=config["configuration"]["model"],
                        temperature=0.2,
                        api_key=config["configuration"]["apiKey"],
                    )
                    break
                elif provider == LLMProvider.GEMINI.value:
                    llm_config = GeminiLLMConfig(
                        model=config["configuration"]["model"],
                        temperature=0.2,
                        api_key=config["configuration"]["apiKey"],
                    )
                elif provider == LLMProvider.ANTHROPIC.value:
                    llm_config = AnthropicLLMConfig(
                        model=config["configuration"]["model"],
                        temperature=0.2,
                        api_key=config["configuration"]["apiKey"],
                    )
                elif provider == LLMProvider.AWS_BEDROCK.value:
                    llm_config = AwsBedrockLLMConfig(
                        model=config["configuration"]["model"],
                        temperature=0.2,
                        region=config["configuration"]["region"],
                        access_key=config["configuration"]["aws_access_key_id"],
                        access_secret=config["configuration"]["aws_access_secret_key"],
                        api_key=config["configuration"]["aws_access_secret_key"],
                    )
                elif provider == LLMProvider.OLLAMA.value:
                    llm_config = OllamaConfig(
                        model=config['configuration']['model'],
                        temperature=0.2,
                        api_key=config['configuration']['apiKey'],
                    )
                elif provider == LLMProvider.OPENAI_COMPATIBLE.value:
                    llm_config = OpenAICompatibleLLMConfig(
                        model=config['configuration']['model'],
                        temperature=0.2,
                        api_key=config['configuration']['apiKey'],
                        endpoint=config['configuration']['endpoint'],
                    )

            if not llm_config:
                raise ValueError("No supported LLM provider found in configuration")

            self.llm = LLMFactory.create_llm(self.logger, llm_config)
            self.logger.info("LLM created successfully")
            return self.llm
        except Exception as e:
            self.logger.error(f"Error getting LLM: {str(e)}")
            return None

    async def get_embedding_model_instance(self, embedding_configs = None) -> Optional[Embeddings]:
        try:
            self.logger.info("Getting embedding model")
            embedding_model = await self.get_embedding_model_instance_from_config(embedding_configs)

            try:
                if not embedding_model or embedding_model == DEFAULT_EMBEDDING_MODEL:
                    self.logger.info("Using default embedding model")
                    embedding_model = DEFAULT_EMBEDDING_MODEL
                    dense_embeddings = await get_default_embedding_model()
                else:
                    self.logger.info(f"Using embedding model: {embedding_model}")
                    dense_embeddings = EmbeddingFactory.create_embedding_model(
                        embedding_model
                    )

            except Exception as e:
                self.logger.error(f"Error creating embedding model: {str(e)}")
                raise EmbeddingModelCreationError(
                    f"Failed to create embedding model: {str(e)}"
                ) from e

            # Get the embedding dimensions from the model
            try:
                sample_embedding = await dense_embeddings.aembed_query("test")
                embedding_size = len(sample_embedding)
            except Exception as e:
                self.logger.warning(
                    f"Error with configured embedding model: {str(e)}"
                )
                raise IndexingError(
                    "Failed to get embedding model: " + str(e),
                )

            self.logger.info(
                f"Using embedding model: {embedding_model}, embedding_size: {embedding_size}"
            )
            return dense_embeddings
        except Exception as e:
            self.logger.error(f"Error getting embedding model: {str(e)}")
            return None

    async def get_embedding_model_instance_from_config(
        self,
        embedding_configs: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[Union[str, AzureEmbeddingConfig, OpenAIEmbeddingConfig,
                       HuggingFaceEmbeddingConfig, SentenceTransformersEmbeddingConfig,
                       GeminiEmbeddingConfig, CohereEmbeddingConfig]]:
        """
        Get embedding model configuration from provided configs or fetch from config service.

        Args:
            embedding_configs: Optional list of embedding configurations

        Returns:
            Either a string for default model, an embedding config object, or None if error occurs
        """
        try:
            if not embedding_configs:
                ai_models = await self.config_service.get_config(
                    config_node_constants.AI_MODELS.value
                )
                embedding_configs = ai_models["embedding"]
            embedding_model = None
            for config in embedding_configs:
                provider = config["provider"]
                if provider == EmbeddingProvider.AZURE_OPENAI.value:
                    embedding_model = AzureEmbeddingConfig(
                        model=config['configuration']['model'],
                        api_key=config['configuration']['apiKey'],
                        azure_endpoint=config['configuration']['endpoint'],
                        azure_api_version=AZURE_EMBEDDING_API_VERSION,
                    )
                elif provider == EmbeddingProvider.OPENAI.value:
                    embedding_model = OpenAIEmbeddingConfig(
                        model=config["configuration"]["model"],
                        api_key=config["configuration"]["apiKey"],
                    )
                elif provider == EmbeddingProvider.HUGGING_FACE.value:
                    embedding_model =   HuggingFaceEmbeddingConfig(
                      model=config['configuration']['model'],
                      api_key=config['configuration']['apiKey'],
                    )
                elif provider == EmbeddingProvider.SENTENCE_TRANSFOMERS.value:
                    embedding_model =   SentenceTransformersEmbeddingConfig(
                      model=config['configuration']['model'],
                    )
                elif provider == EmbeddingProvider.GEMINI.value:
                    embedding_model = GeminiEmbeddingConfig(
                      model=config['configuration']['model'],
                      api_key=config['configuration']['apiKey'],
                    )
                elif provider == EmbeddingProvider.COHERE.value:
                    embedding_model = CohereEmbeddingConfig(
                      model=config['configuration']['model'],
                      api_key=config['configuration']['apiKey'],
                    )
                elif provider == EmbeddingProvider.OPENAI_COMPATIBLE.value:
                    embedding_model = OpenAICompatibleEmbeddingConfig(
                      model=config['configuration']['model'],
                      api_key=config['configuration']['apiKey'],
                      organization_id=config['configuration'].get('organizationId', None),
                      endpoint=config['configuration']['endpoint'],
                    )
                elif provider == EmbeddingProvider.DEFAULT.value:
                    embedding_model = DEFAULT_EMBEDDING_MODEL

            return embedding_model
        except Exception as e:
            self.logger.error(f"Error getting embedding model: {str(e)}")
            return None

    async def get_current_embedding_model_name(self) -> Optional[str]:
        """Get the current embedding model name from configuration or instance."""
        try:
            # First try to get from AI_MODELS config
            ai_models = await self.config_service.get_config(
                config_node_constants.AI_MODELS.value
            )
            if ai_models and "embedding" in ai_models and ai_models["embedding"]:
                for config in ai_models["embedding"]:
                    # Only one embedding model is supported
                    if "configuration" in config and "model" in config["configuration"]:
                        return config["configuration"]["model"]

            # Return default model if no embedding config found
            return DEFAULT_EMBEDDING_MODEL
        except Exception as e:
            self.logger.error(f"Error getting current embedding model name: {str(e)}")
            return DEFAULT_EMBEDDING_MODEL

    def get_embedding_model_name(self, dense_embeddings: Embeddings) -> Optional[str]:
        if hasattr(dense_embeddings, "model_name"):
            return dense_embeddings.model_name
        elif hasattr(dense_embeddings, "model"):
            return dense_embeddings.model
        else:
            return None

    async def _preprocess_query(self, query: str) -> str:
        """
        Preprocess the query text.

        Args:
            query: Raw query text

        Returns:
            Preprocessed query text
        """
        try:
            # Get current model name from config
            model_name = await self.get_current_embedding_model_name()

            # Check if using BGE model before adding the prefix
            if model_name and "bge" in model_name.lower():
                return f"Represent this document for retrieval: {query.strip()}"
            return query.strip()
        except Exception as e:
            self.logger.error(f"Error in query preprocessing: {str(e)}")
            return query.strip()

    def _format_results(self, results: List[tuple]) -> List[Dict[str, Any]]:
        """Format search results into a consistent structure with flattened metadata."""
        formatted_results = []
        for doc, score in results:
            formatted_result = {
                "content": doc.page_content,
                "score": float(score),
                "citationType": "vectordb|document",
                "metadata": doc.metadata,
            }
            formatted_results.append(formatted_result)
        return formatted_results

    async def _build_qdrant_filter(
        self, org_id: str, accessible_records: List[str], arango_service: ArangoService
    ) -> Filter:
        """
        Build Qdrant filter for accessible records with both org_id and record_id conditions.

        Args:
            org_id: Organization ID to filter
            accessible_records: List of record IDs the user has access to

        Returns:
            Qdrant Filter object
        """
        virtual_record_ids = []
        for record_id in accessible_records:
            record = await arango_service.get_document(
                record_id, CollectionNames.RECORDS.value
            )
            if record.get("virtualRecordId"):
                virtual_record_ids.append(record.get("virtualRecordId"))

        return Filter(
            must=[
                FieldCondition(  # org_id condition
                    key="metadata.orgId", match=MatchValue(value=org_id)
                ),
                Filter(  # recordId must be one of the accessible_records
                    should=[
                        FieldCondition(
                            key="metadata.virtualRecordId", match=MatchValue(value=virtual_record_id)
                        )
                        for virtual_record_id in virtual_record_ids
                    ]
                ),
            ]
        )

    async def search_with_filters(
        self,
        queries: List[str],
        user_id: str,
        org_id: str,
        filter_groups: Optional[Dict[str, List[str]]] = None,
        limit: int = 20,
        arango_service: Optional[ArangoService] = None,
    ) -> List[Dict[str, Any]]:
        """Perform semantic search on accessible records with multiple queries."""

        try:
            # Get accessible records
            if not arango_service:
                raise ValueError("ArangoService is required for permission checking")

            filter_groups = filter_groups or {}

            # Convert filter_groups to format expected by get_accessible_records
            arango_filters = {}
            if filter_groups:  # Only process if filter_groups is not empty
                for key, values in filter_groups.items():
                    # Convert key to match collection naming
                    metadata_key = (
                        key.lower()
                    )  # e.g., 'departments', 'categories', etc.
                    arango_filters[metadata_key] = values

            accessible_records = await arango_service.get_accessible_records(
                user_id=user_id, org_id=org_id, filters=arango_filters
            )

            if not accessible_records:
                self.logger.info(
                    "No accessible records found for this user with provided filters."
                )
                return {
                    "searchResults": [],
                    "records": [],
                    "status": Status.ACCESSIBLE_RECORDS_NOT_FOUND.value,
                    "status_code": 200,
                    "message": "No accessible records found for this user with provided filters.",
                }

            # Extract record IDs from accessible records
            accessible_record_ids = [
                record["_key"] for record in accessible_records if record is not None
            ]
            # Build Qdrant filter
            qdrant_filter = await self._build_qdrant_filter(org_id, accessible_record_ids, arango_service)

            all_results = []
            seen_chunks = set()

            if not self.vector_store:
                # Check if collection exists and is not empty in Qdrant
                try:
                    collections = self.qdrant_client.get_collections()
                    collection_info = (
                        self.qdrant_client.get_collection(self.collection_name)
                        if any(
                            col.name == self.collection_name
                            for col in collections.collections
                        )
                        else None
                    )
                except Exception as e:
                    self.logger.warning(
                        f"Collection {self.collection_name} not found in Qdrant: {str(e)}"
                    )
                    return {
                        "searchResults": [],
                        "records": [],
                        "status": Status.VECTOR_DB_NOT_READY.value,
                        "status_code": 200,
                        "message": "Vector DB is empty. No records available for retrieval.",
                    }

                if not collection_info or collection_info.points_count == 0:
                    self.logger.info(
                        f"Collection {self.collection_name} not found in Qdrant or is empty. Indexing may not be complete."
                    )
                    return {
                        "searchResults": [],
                        "records": [],
                        "status": Status.VECTOR_DB_EMPTY.value,
                        "status_code": 200,
                        "message": "Vector DB is empty. No records available for retrieval.",
                    }

                dense_embeddings = await self.get_embedding_model_instance()
                if not dense_embeddings:
                    raise ValueError(
                        "No dense embeddings found, please configure an embedding model or ensure indexing is complete"
                    )

                self.logger.info("Dense embeddings: %s", dense_embeddings)
                self.vector_store = QdrantVectorStore(
                    client=self.qdrant_client,
                    collection_name=self.collection_name,
                    vector_name="dense",
                    sparse_vector_name="sparse",
                    embedding=dense_embeddings,
                    sparse_embedding=self.sparse_embeddings,
                    retrieval_mode=RetrievalMode.HYBRID,
                )

            # Process each query
            for query in queries:
                # Perform similarity search
                processed_query = await self._preprocess_query(query)
                results = await self.vector_store.asimilarity_search_with_score(
                    query=processed_query, k=limit, filter=qdrant_filter
                )
                # Add to results if content not already seen
                for doc, score in results:
                    if doc.page_content not in seen_chunks:
                        all_results.append((doc, score))
                        seen_chunks.add(doc.page_content)

            search_results = self._format_results(all_results)

            # Create mapping of virtualRecordId to first accessible record ID
            virtual_to_record_map = {}
            virtual_record_ids = list(
                set(result["metadata"]["virtualRecordId"] for result in search_results)
            )

            # Get all record IDs for these virtual record IDs
            all_record_ids = []
            for virtual_record_id in virtual_record_ids:
                record_ids = await arango_service.get_records_by_virtual_record_id(
                    virtual_record_id,
                    accessible_record_ids=accessible_record_ids
                )
                if record_ids:  # Only add if we found accessible records
                    virtual_to_record_map[virtual_record_id] = record_ids[0]  # Use first record ID
                    all_record_ids.extend(record_ids)

            # Convert to set to remove any duplicates
            unique_record_ids = set(all_record_ids)
            user = await arango_service.get_user_by_user_id(user_id)

            # Replace virtualRecordId with first accessible record ID in search results
            for result in search_results:
                virtual_id = result["metadata"]["virtualRecordId"]
                if virtual_id in virtual_to_record_map:
                    record_id = virtual_to_record_map[virtual_id]
                    result["metadata"]["recordId"] = record_id
                    record = await arango_service.get_document(
                        record_id, CollectionNames.RECORDS.value
                    )
                    result["metadata"]["origin"] = record.get("origin")
                    result["metadata"]["connector"] = record.get("connectorName")

                    if record.get("recordType", "") == RecordTypes.FILE.value:
                        files = await arango_service.get_document(
                            record_id, CollectionNames.FILES.value
                        )
                        weburl = files.get("webUrl")
                        if weburl and record.get("connectorName", "") == Connectors.GOOGLE_MAIL.value:
                            weburl = weburl.replace("{user.email}", user["email"])
                        result["metadata"]["webUrl"] = weburl

                    if record.get("recordType", "") == RecordTypes.MAIL.value:
                        mail = await arango_service.get_document(
                            record_id, CollectionNames.MAILS.value
                        )
                        weburl = mail.get("webUrl")
                        if weburl:
                            weburl = weburl.replace("{user.email}", user["email"])
                        result["metadata"]["webUrl"] = weburl

            # Get full record documents from Arango
            records = []
            if unique_record_ids:
                for record_id in unique_record_ids:
                    record = await arango_service.get_document(
                        record_id, CollectionNames.RECORDS.value
                    )
                    if record.get("recordType", "") == RecordTypes.FILE.value:
                        files = await arango_service.get_document(
                            record_id, CollectionNames.FILES.value
                        )
                        if record.get("connectorName", "") == Connectors.GOOGLE_MAIL.value:
                            weburl = files.get("webUrl")
                            weburl = weburl.replace("{user.email}", user["email"])
                            files["webUrl"] = weburl
                        record = {**record, **files}
                    if record.get("recordType", "") == RecordTypes.MAIL.value:
                        mail = await arango_service.get_document(
                            record_id, CollectionNames.MAILS.value
                        )
                        weburl = mail.get("webUrl")
                        weburl = weburl.replace("{user.email}", user["email"])
                        mail["webUrl"] = weburl
                        record = {**record, **mail}
                    records.append(record)

            if search_results or records:
                return {
                    "searchResults": search_results,
                    "records": records,
                    "status": Status.SUCCESS.value,
                    "status_code": 200,
                    "message": "Query processed successfully. Relevant records retrieved.",
                }
            else:
                return {
                    "searchResults": [],
                    "records": [],
                    "status": Status.EMPTY_RESPONSE.value,
                    "status_code": 200,
                    "message": "Query processed, but no relevant results were found.",
                }

        except Exception as e:
            self.logger.error(f"Filtered search failed: {str(e)}")
            return {
                "searchResults": [],
                "records": [],
                "status": Status.ERROR.value,
                "status_code": 500,
                "message": f"An error occurred during search: {str(e)}",
            }
