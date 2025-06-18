import React, { useState, useCallback, useRef } from 'react';
import {
  Box,
  Button,
  Typography,
  LinearProgress,
  Alert,
  Chip,
  IconButton,
  Paper,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  ListItemSecondaryAction,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Tooltip,
} from '@mui/material';
import {
  CloudUpload as UploadIcon,
  AttachFile as AttachIcon,
  Description as DocIcon,
  PictureAsPdf as PdfIcon,
  TableChart as ExcelIcon,
  Code as CodeIcon,
  Delete as DeleteIcon,
  CheckCircle as CheckIcon,
  Error as ErrorIcon,
} from '@mui/icons-material';

import { useAuthContext } from 'src/auth/hooks';
import { axiosInstance } from 'src/utils/axios';

// Types
interface UploadedDocument {
  document_id: string;
  filename: string;
  status: 'uploading' | 'success' | 'error';
  message: string;
  processing_time_ms?: number;
  indexed_chunks?: number;
  error?: string;
}

interface DocumentUploadProps {
  conversationId: string;
  onDocumentUploaded: (document: UploadedDocument) => void;
  onDocumentRemoved: (documentId: string) => void;
  uploadedDocuments: UploadedDocument[];
  maxFiles?: number;
}

const DocumentUpload: React.FC<DocumentUploadProps> = ({
  conversationId,
  onDocumentUploaded,
  onDocumentRemoved,
  uploadedDocuments,
  maxFiles = 10,
}) => {
  const { user } = useAuthContext();
  const fileInputRef = useRef<HTMLInputElement>(null);
  
  const [dragActive, setDragActive] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<Record<string, number>>({});
  const [showUploadDialog, setShowUploadDialog] = useState(false);

  const allowedTypes = [
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-excel',
    'text/csv',
    'text/plain',
    'text/html',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  ];

  const allowedExtensions = ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.csv', '.txt', '.html', '.pptx'];

  const getFileIcon = (filename: string) => {
    const ext = filename.toLowerCase().split('.').pop();
    switch (ext) {
      case 'pdf':
        return <PdfIcon color="error" />;
      case 'docx':
      case 'doc':
        return <DocIcon color="primary" />;
      case 'xlsx':
      case 'xls':
      case 'csv':
        return <ExcelIcon color="success" />;
      default:
        return <CodeIcon color="action" />;
    }
  };

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFiles(Array.from(e.dataTransfer.files));
    }
  }, []);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      handleFiles(Array.from(e.target.files));
    }
  }, []);

  const validateFile = (file: File): string | null => {
    // Check file type
    if (!allowedTypes.includes(file.type)) {
      const ext = '.' + file.name.toLowerCase().split('.').pop();
      if (!allowedExtensions.includes(ext)) {
        return `File type not supported. Allowed types: ${allowedExtensions.join(', ')}`;
      }
    }

    // Check file size (max 50MB)
    if (file.size > 50 * 1024 * 1024) {
      return 'File size must be less than 50MB';
    }

    // Check if we're at max files
    if (uploadedDocuments.length >= maxFiles) {
      return `Maximum ${maxFiles} files allowed`;
    }

    return null;
  };

  const handleFiles = useCallback(async (files: File[]) => {
    for (const file of files) {
      const validationError = validateFile(file);
      if (validationError) {
        const errorDoc: UploadedDocument = {
          document_id: `error-${Date.now()}`,
          filename: file.name,
          status: 'error',
          message: validationError,
          error: validationError,
        };
        onDocumentUploaded(errorDoc);
        continue;
      }

      const tempId = `temp-${Date.now()}-${file.name}`;
      const uploadingDoc: UploadedDocument = {
        document_id: tempId,
        filename: file.name,
        status: 'uploading',
        message: 'Uploading and processing...',
      };
      
      onDocumentUploaded(uploadingDoc);
      setUploadProgress(prev => ({ ...prev, [tempId]: 0 }));

      try {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('conversation_id', conversationId);
        formData.append('auto_index', 'true');

        const response = await axiosInstance.post(
          '/api/v1/chat-documents/upload-and-index',
          formData,
          {
            headers: {
              'Content-Type': 'multipart/form-data',
            },
            onUploadProgress: (progressEvent) => {
              if (progressEvent.total) {
                const percentCompleted = Math.round(
                  (progressEvent.loaded * 100) / progressEvent.total
                );
                setUploadProgress(prev => ({ ...prev, [tempId]: percentCompleted }));
              }
            },
          }
        );

        const successDoc: UploadedDocument = {
          document_id: response.data.document_id,
          filename: file.name,
          status: 'success',
          message: response.data.message,
          processing_time_ms: response.data.processing_time_ms,
          indexed_chunks: response.data.indexed_chunks,
        };

        // Remove the temporary uploading document and add the successful one
        onDocumentRemoved(tempId);
        onDocumentUploaded(successDoc);
        
      } catch (error: any) {
        const errorDoc: UploadedDocument = {
          document_id: tempId,
          filename: file.name,
          status: 'error',
          message: error.response?.data?.detail || 'Upload failed',
          error: error.response?.data?.detail || 'Upload failed',
        };
        
        // Update the uploading document to error status
        onDocumentRemoved(tempId);
        onDocumentUploaded(errorDoc);
      } finally {
        setUploadProgress(prev => {
          const newProgress = { ...prev };
          delete newProgress[tempId];
          return newProgress;
        });
      }
    }
  }, [conversationId, uploadedDocuments.length, maxFiles, onDocumentUploaded, onDocumentRemoved]);

  const handleRemoveDocument = useCallback(async (documentId: string) => {
    try {
      await axiosInstance.delete(`/api/v1/chat-documents/document/${documentId}`);
      onDocumentRemoved(documentId);
    } catch (error) {
      console.error('Failed to remove document:', error);
      // Still remove from UI even if API call fails
      onDocumentRemoved(documentId);
    }
  }, [onDocumentRemoved]);

  const openFileDialog = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  return (
    <Box>
      {/* Upload Area */}
      <Paper
        sx={{
          p: 2,
          border: dragActive ? '2px dashed #1976d2' : '2px dashed #ccc',
          borderRadius: 2,
          backgroundColor: dragActive ? 'action.hover' : 'background.paper',
          cursor: 'pointer',
          transition: 'all 0.2s ease',
          '&:hover': {
            borderColor: 'primary.main',
            backgroundColor: 'action.hover',
          },
        }}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        onClick={openFileDialog}
      >
        <Box sx={{ textAlign: 'center' }}>
          <UploadIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 1 }} />
          <Typography variant="h6" gutterBottom>
            Add Documents to Chat
          </Typography>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            Drag and drop files here, or click to browse
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Supported formats: PDF, DOCX, XLSX, CSV, TXT, HTML, PPTX (max 50MB)
          </Typography>
        </Box>
      </Paper>

      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={allowedExtensions.join(',')}
        onChange={handleFileSelect}
        style={{ display: 'none' }}
      />

      {/* Uploaded Documents List */}
      {uploadedDocuments.length > 0 && (
        <Box sx={{ mt: 2 }}>
          <Typography variant="subtitle2" gutterBottom>
            Documents in this conversation ({uploadedDocuments.length}/{maxFiles})
          </Typography>
          <List dense>
            {uploadedDocuments.map((doc) => (
              <ListItem
                key={doc.document_id}
                sx={{
                  border: '1px solid',
                  borderColor: 'divider',
                  borderRadius: 1,
                  mb: 1,
                  backgroundColor: 
                    doc.status === 'success' ? 'success.lighter' :
                    doc.status === 'error' ? 'error.lighter' : 'background.paper'
                }}
              >
                <ListItemIcon>
                  {doc.status === 'uploading' ? (
                    <Box sx={{ position: 'relative', display: 'inline-flex' }}>
                      {getFileIcon(doc.filename)}
                    </Box>
                  ) : doc.status === 'success' ? (
                    <CheckIcon color="success" />
                  ) : (
                    <ErrorIcon color="error" />
                  )}
                </ListItemIcon>
                
                <ListItemText
                  primary={doc.filename}
                  secondary={
                    <Box>
                      <Typography variant="caption" color="text.secondary">
                        {doc.message}
                      </Typography>
                      {doc.processing_time_ms && (
                        <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                          • Processed in {doc.processing_time_ms}ms
                        </Typography>
                      )}
                      {doc.indexed_chunks && (
                        <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                          • {doc.indexed_chunks} chunks indexed
                        </Typography>
                      )}
                      {doc.status === 'uploading' && uploadProgress[doc.document_id] !== undefined && (
                        <LinearProgress
                          variant="determinate"
                          value={uploadProgress[doc.document_id]}
                          sx={{ mt: 0.5 }}
                        />
                      )}
                    </Box>
                  }
                />
                
                <ListItemSecondaryAction>
                  {doc.status !== 'uploading' && (
                    <Tooltip title="Remove document">
                      <IconButton
                        edge="end"
                        size="small"
                        onClick={() => handleRemoveDocument(doc.document_id)}
                      >
                        <DeleteIcon />
                      </IconButton>
                    </Tooltip>
                  )}
                </ListItemSecondaryAction>
              </ListItem>
            ))}
          </List>
        </Box>
      )}

      {/* Quick Actions */}
      <Box sx={{ mt: 2, display: 'flex', gap: 1, flexWrap: 'wrap' }}>
        <Button
          size="small"
          startIcon={<AttachIcon />}
          onClick={openFileDialog}
          disabled={uploadedDocuments.length >= maxFiles}
        >
          Add Files
        </Button>
        
        {uploadedDocuments.some(doc => doc.status === 'success') && (
          <Chip
            size="small"
            label={`${uploadedDocuments.filter(doc => doc.status === 'success').length} documents ready`}
            color="success"
            variant="outlined"
          />
        )}
      </Box>
    </Box>
  );
};

export default DocumentUpload; 