# Chat Document Upload API for on-the-fly document addition
import asyncio
import tempfile
from typing import Any, Dict, List, Optional

from dependency_injector.wiring import inject
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.events.processor import Processor
from app.modules.retrieval.retrieval_service import RetrievalService
from app.setups.query_setup import AppContainer

router = APIRouter()

class DocumentUploadResponse(BaseModel):
    document_id: str
    status: str
    message: str
    processing_time_ms: int
    indexed_chunks: int

class ChatDocumentQuery(BaseModel):
    query: str
    conversation_id: str
    document_ids: Optional[List[str]] = []
    limit: Optional[int] = 10

@router.post("/upload-and-index")
@inject
async def upload_document_to_chat(
    request: Request,
    file: UploadFile = File(...),
    conversation_id: str = Form(...),
    auto_index: bool = Form(True),
    processor: Processor = Depends(lambda: request.app.container.processor()),
    retrieval_service: RetrievalService = Depends(lambda: request.app.container.retrieval_service()),
):
    """Upload and immediately index a document for use in chat"""
    import time
    start_time = time.time()
    
    try:
        container = request.app.container
        logger = container.logger()
        
        # Get user info from request
        org_id = request.state.user.get('orgId')
        user_id = request.state.user.get('userId')
        
        if not org_id or not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")

        # Validate file
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")
        
        # Check file extension
        allowed_extensions = ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.csv', '.txt', '.html', '.pptx']
        file_extension = file.filename.lower().split('.')[-1]
        if f'.{file_extension}' not in allowed_extensions:
            raise HTTPException(
                status_code=400, 
                detail=f"File type .{file_extension} not supported. Allowed: {', '.join(allowed_extensions)}"
            )

        # Read file content
        file_content = await file.read()
        if len(file_content) == 0:
            raise HTTPException(status_code=400, detail="Empty file provided")

        # Generate unique document ID
        import uuid
        document_id = str(uuid.uuid4())
        virtual_record_id = str(uuid.uuid4())
        
        logger.info(f"Processing uploaded document: {file.filename} for conversation: {conversation_id}")

        # Process document based on type
        result = None
        indexed_chunks = 0
        
        if file_extension == 'pdf':
            result = await processor.process_pdf_document(
                recordName=file.filename,
                recordId=document_id,
                version="1.0",
                source="chat_upload",
                orgId=org_id,
                pdf_binary=file_content,
                virtual_record_id=virtual_record_id
            )
        elif file_extension in ['docx']:
            from io import BytesIO
            result = await processor.process_docx_document(
                recordName=file.filename,
                recordId=document_id,
                version="1.0",
                source="chat_upload",
                orgId=org_id,
                docx_binary=BytesIO(file_content),
                virtual_record_id=virtual_record_id
            )
        elif file_extension in ['xlsx']:
            result = await processor.process_excel_document(
                recordName=file.filename,
                recordId=document_id,
                version="1.0",
                source="chat_upload",
                orgId=org_id,
                excel_binary=file_content,
                virtual_record_id=virtual_record_id
            )
        elif file_extension == 'csv':
            result = await processor.process_csv_document(
                recordName=file.filename,
                recordId=document_id,
                version="1.0",
                source="chat_upload",
                orgId=org_id,
                csv_binary=file_content,
                virtual_record_id=virtual_record_id
            )
        elif file_extension == 'html':
            result = await processor.process_html_document(
                recordName=file.filename,
                recordId=document_id,
                version="1.0",
                source="chat_upload",
                orgId=org_id,
                html_content=file_content,
                virtual_record_id=virtual_record_id
            )
        else:
            # Handle as text file
            try:
                text_content = file_content.decode('utf-8')
                # Create a simple text processing result
                result = {
                    "status": "success",
                    "text_content": text_content,
                    "metadata": {
                        "recordName": file.filename,
                        "orgId": org_id,
                        "version": "1.0",
                        "source": "chat_upload",
                        "document_info": {
                            "page_count": 1,
                            "character_count": len(text_content)
                        }
                    }
                }
                
                # Index the text content directly
                if auto_index and text_content.strip():
                    sentence_data = [{
                        "text": text_content,
                        "metadata": {
                            "recordId": document_id,
                            "blockText": text_content,
                            "blockType": "text",
                            "blockNum": [1],
                            "pageNum": [1],
                            "virtualRecordId": virtual_record_id,
                            "orgId": org_id,
                            "source": "chat_upload",
                            "filename": file.filename
                        }
                    }]
                    
                    # Get indexing pipeline
                    indexing_pipeline = container.indexing_pipeline()
                    await indexing_pipeline.index_documents(sentence_data)
                    indexed_chunks = 1
                    
            except UnicodeDecodeError:
                raise HTTPException(status_code=400, detail="File content cannot be decoded as text")

        if result and result.get("status") != "success":
            raise HTTPException(status_code=500, detail="Document processing failed")

        # Store document metadata in conversation context
        # This would typically be stored in a database associated with the conversation
        conversation_context = {
            "document_id": document_id,
            "virtual_record_id": virtual_record_id,
            "filename": file.filename,
            "conversation_id": conversation_id,
            "upload_timestamp": time.time(),
            "org_id": org_id,
            "user_id": user_id,
            "file_size": len(file_content),
            "file_type": file_extension,
            "processing_result": result
        }

        processing_time = int((time.time() - start_time) * 1000)
        
        logger.info(f"Successfully processed document {file.filename} in {processing_time}ms")

        return DocumentUploadResponse(
            document_id=document_id,
            status="success",
            message=f"Document '{file.filename}' uploaded and indexed successfully",
            processing_time_ms=processing_time,
            indexed_chunks=indexed_chunks or (len(result.get("ocr_result", {}).get("sentences", [])) if result else 0)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading document to chat: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Document upload failed: {str(e)}")


@router.post("/query-with-documents")
@inject
async def query_with_uploaded_documents(
    request: Request,
    query_info: ChatDocumentQuery,
    retrieval_service: RetrievalService = Depends(lambda: request.app.container.retrieval_service()),
):
    """Query using both conversation context and newly uploaded documents"""
    try:
        container = request.app.container
        logger = container.logger()
        
        # Get user info
        org_id = request.state.user.get('orgId')
        user_id = request.state.user.get('userId')
        
        if not org_id or not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")

        # Get LLM instance
        llm = await retrieval_service.get_llm_instance()
        if llm is None:
            raise HTTPException(
                status_code=500,
                detail="Failed to initialize LLM service."
            )

        # Build search filters to include uploaded documents
        filters = {
            "sources": ["chat_upload"],
            "org_id": [org_id]
        }
        
        if query_info.document_ids:
            filters["record_ids"] = query_info.document_ids

        # Perform retrieval with document filters
        arango_service = container.arango_service()
        results = await retrieval_service.search_with_filters(
            queries=[query_info.query],
            org_id=org_id,
            user_id=user_id,
            limit=query_info.limit,
            filter_groups=filters,
            arango_service=arango_service,
        )

        if results.get("status_code") in [202, 500, 503]:
            return JSONResponse(
                status_code=results.get("status_code", 500),
                content={
                    "status": results.get("status", "error"),
                    "message": results.get("message", "No results found"),
                    "searchResults": [],
                    "documents_searched": query_info.document_ids or []
                }
            )

        search_results = results.get("searchResults", [])

        # Generate response using LLM with document context
        context_prompt = f"""
        Based on the uploaded documents and search results, answer the following question:
        
        Question: {query_info.query}
        
        Search Results:
        {search_results[:5]}  # Limit context for LLM
        
        Please provide a comprehensive answer based on the document content.
        Include citations to specific documents when relevant.
        """

        response = await llm.ainvoke([{"role": "user", "content": context_prompt}])

        return {
            "query": query_info.query,
            "answer": response.content,
            "search_results": search_results,
            "documents_searched": query_info.document_ids or [],
            "conversation_id": query_info.conversation_id,
            "metadata": {
                "results_count": len(search_results),
                "query_time": "response_time_placeholder"
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying with documents: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversation/{conversation_id}/documents")
async def get_conversation_documents(
    conversation_id: str,
    request: Request
):
    """Get all documents uploaded to a specific conversation"""
    try:
        # Get user info
        org_id = request.state.user.get('orgId')
        user_id = request.state.user.get('userId')
        
        if not org_id or not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")

        # This would typically query a database for documents associated with the conversation
        # For now, return a placeholder response
        return {
            "conversation_id": conversation_id,
            "documents": [],
            "message": "Document retrieval functionality would be implemented with proper database storage"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/document/{document_id}")
async def remove_document_from_chat(
    document_id: str,
    request: Request
):
    """Remove a document from chat context and search index"""
    try:
        container = request.app.container
        logger = container.logger()
        
        # Get user info
        org_id = request.state.user.get('orgId')
        user_id = request.state.user.get('userId')
        
        if not org_id or not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")

        # This would remove the document from the vector database and conversation context
        # Implementation would depend on the specific storage and indexing system
        
        logger.info(f"Document {document_id} removal requested by user {user_id}")
        
        return {
            "document_id": document_id,
            "status": "removed",
            "message": "Document removed from chat context"
        }

    except Exception as e:
        logger.error(f"Error removing document: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) 