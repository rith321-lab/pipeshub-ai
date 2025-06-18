import React, { useState, useCallback, useEffect } from 'react';
import {
  Box,
  Card,
  CardContent,
  CardHeader,
  Typography,
  TextField,
  Button,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Grid,
  Alert,
  Chip,
  Divider,
  CircularProgress,
  Paper,
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  IconButton,
  Tooltip,
} from '@mui/material';
import {
  PlayArrow as PlayIcon,
  Refresh as RefreshIcon,
  Download as DownloadIcon,
  Analytics as AnalyticsIcon,
  Storage as DatabaseIcon,
} from '@mui/icons-material';
import Plot from 'react-plotly.js';

import { useAuthContext } from 'src/auth/hooks';
import { axiosInstance } from 'src/utils/axios';

// Types
interface SQLQueryResult {
  sql_query: string;
  data: any[];
  chart: {
    plotly_json: string;
    chart_type: string;
    x_column: string;
    y_column: string;
    error?: string;
  };
  insights: string;
  metadata: {
    row_count: number;
    columns: string[];
    chart_type: string;
  };
}

interface PredictiveAnalysis {
  predictions: string;
  trends: Record<string, {
    direction: string;
    change_percentage: number;
  }>;
  data_summary: {
    row_count: number;
    columns: string[];
    numeric_columns: string[];
  };
}

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props;

  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`sql-tabpanel-${index}`}
      aria-labelledby={`sql-tab-${index}`}
      {...other}
    >
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  );
}

const SQLExplorer: React.FC = () => {
  const { user } = useAuthContext();
  
  // State management
  const [naturalLanguageQuery, setNaturalLanguageQuery] = useState('');
  const [sqlQuery, setSqlQuery] = useState('');
  const [databaseConnection, setDatabaseConnection] = useState('');
  const [chartType, setChartType] = useState('auto');
  const [isLoading, setIsLoading] = useState(false);
  const [queryResult, setQueryResult] = useState<SQLQueryResult | null>(null);
  const [predictiveAnalysis, setPredictiveAnalysis] = useState<PredictiveAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState(0);
  const [savedConnections, setSavedConnections] = useState<string[]>([
    'postgresql://user:pass@localhost:5432/database',
    'mysql://user:pass@localhost:3306/database',
    'sqlite:///path/to/database.db'
  ]);

  // Sample queries for demonstration
  const sampleQueries = [
    "Show me the top 10 customers by revenue this year",
    "What are the sales trends over the last 6 months?",
    "Which products have the highest profit margins?",
    "Show me user engagement metrics by region",
    "What's the monthly growth rate of our active users?"
  ];

  const chartTypes = [
    { value: 'auto', label: 'Auto-select' },
    { value: 'bar', label: 'Bar Chart' },
    { value: 'line', label: 'Line Chart' },
    { value: 'scatter', label: 'Scatter Plot' },
    { value: 'pie', label: 'Pie Chart' },
    { value: 'histogram', label: 'Histogram' },
    { value: 'box', label: 'Box Plot' },
    { value: 'none', label: 'No Chart' }
  ];

  const handleTabChange = (event: React.SyntheticEvent, newValue: number) => {
    setActiveTab(newValue);
  };

  const executeQuery = useCallback(async () => {
    if (!naturalLanguageQuery.trim() && !sqlQuery.trim()) {
      setError('Please enter either a natural language query or SQL query');
      return;
    }

    if (!databaseConnection.trim()) {
      setError('Please provide a database connection string');
      return;
    }

    setIsLoading(true);
    setError(null);
    setQueryResult(null);
    setPredictiveAnalysis(null);

    try {
      const response = await axiosInstance.post('/api/v1/sql/execute-sql', {
        query: sqlQuery,
        database_connection: databaseConnection,
        natural_language_query: naturalLanguageQuery,
        chart_type: chartType,
        limit: 1000
      });

      setQueryResult(response.data);
      setActiveTab(0); // Switch to results tab
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to execute query');
    } finally {
      setIsLoading(false);
    }
  }, [naturalLanguageQuery, sqlQuery, databaseConnection, chartType]);

  const generatePredictiveAnalysis = useCallback(async () => {
    if (!queryResult) {
      setError('Please execute a query first');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const response = await axiosInstance.post('/api/v1/sql/generate-predictive-analysis', {
        query: queryResult.sql_query,
        database_connection: databaseConnection,
        natural_language_query: naturalLanguageQuery,
        chart_type: chartType
      });

      setPredictiveAnalysis(response.data);
      setActiveTab(2); // Switch to predictions tab
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to generate predictive analysis');
    } finally {
      setIsLoading(false);
    }
  }, [queryResult, databaseConnection, naturalLanguageQuery, chartType]);

  const handleSampleQuery = (query: string) => {
    setNaturalLanguageQuery(query);
    setSqlQuery(''); // Clear SQL query when using natural language
  };

  const downloadResults = () => {
    if (!queryResult?.data) return;

    const csv = [
      queryResult.metadata.columns.join(','),
      ...queryResult.data.map(row => 
        queryResult.metadata.columns.map(col => row[col] || '').join(',')
      )
    ].join('\n');

    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'query_results.csv';
    a.click();
    window.URL.revokeObjectURL(url);
  };

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" gutterBottom>
        SQL Explorer with AI Insights
      </Typography>
      <Typography variant="body1" color="text.secondary" gutterBottom>
        Explore your relational data using natural language queries, generate interactive charts, and get AI-powered insights.
      </Typography>

      <Grid container spacing={3}>
        {/* Query Input Section */}
        <Grid item xs={12} md={6}>
          <Card>
            <CardHeader 
              title="Query Builder" 
              avatar={<DatabaseIcon color="primary" />}
            />
            <CardContent>
              <Box sx={{ mb: 2 }}>
                <FormControl fullWidth>
                  <InputLabel>Database Connection</InputLabel>
                  <Select
                    value={databaseConnection}
                    onChange={(e) => setDatabaseConnection(e.target.value)}
                    label="Database Connection"
                  >
                    {savedConnections.map((conn, index) => (
                      <MenuItem key={index} value={conn}>
                        {conn}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Box>

              <TextField
                fullWidth
                multiline
                rows={4}
                label="Natural Language Query"
                value={naturalLanguageQuery}
                onChange={(e) => setNaturalLanguageQuery(e.target.value)}
                placeholder="e.g., Show me the top 10 customers by revenue this year"
                sx={{ mb: 2 }}
              />

              <Typography variant="body2" sx={{ mb: 1 }}>
                Or write SQL directly:
              </Typography>
              <TextField
                fullWidth
                multiline
                rows={4}
                label="SQL Query"
                value={sqlQuery}
                onChange={(e) => setSqlQuery(e.target.value)}
                placeholder="SELECT * FROM customers ORDER BY revenue DESC LIMIT 10"
                sx={{ mb: 2 }}
              />

              <FormControl fullWidth sx={{ mb: 2 }}>
                <InputLabel>Chart Type</InputLabel>
                <Select
                  value={chartType}
                  onChange={(e) => setChartType(e.target.value)}
                  label="Chart Type"
                >
                  {chartTypes.map((type) => (
                    <MenuItem key={type.value} value={type.value}>
                      {type.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>

              <Box sx={{ display: 'flex', gap: 1 }}>
                <Button
                  variant="contained"
                  startIcon={<PlayIcon />}
                  onClick={executeQuery}
                  disabled={isLoading}
                  fullWidth
                >
                  {isLoading ? <CircularProgress size={20} /> : 'Execute Query'}
                </Button>
                {queryResult && (
                  <Button
                    variant="outlined"
                    startIcon={<AnalyticsIcon />}
                    onClick={generatePredictiveAnalysis}
                    disabled={isLoading}
                  >
                    Predict
                  </Button>
                )}
              </Box>
            </CardContent>
          </Card>
        </Grid>

        {/* Sample Queries */}
        <Grid item xs={12} md={6}>
          <Card>
            <CardHeader title="Sample Queries" />
            <CardContent>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Click on any sample query to get started:
              </Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                {sampleQueries.map((query, index) => (
                  <Chip
                    key={index}
                    label={query}
                    onClick={() => handleSampleQuery(query)}
                    variant="outlined"
                    sx={{ 
                      justifyContent: 'flex-start',
                      height: 'auto',
                      padding: 1,
                      '& .MuiChip-label': {
                        whiteSpace: 'normal',
                        textAlign: 'left'
                      }
                    }}
                  />
                ))}
              </Box>
            </CardContent>
          </Card>
        </Grid>

        {/* Results Section */}
        <Grid item xs={12}>
          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}

          {(queryResult || predictiveAnalysis) && (
            <Card>
              <CardHeader 
                title="Results" 
                action={
                  queryResult && (
                    <Tooltip title="Download Results">
                      <IconButton onClick={downloadResults}>
                        <DownloadIcon />
                      </IconButton>
                    </Tooltip>
                  )
                }
              />
              <CardContent>
                <Tabs value={activeTab} onChange={handleTabChange}>
                  <Tab label="Data & Chart" />
                  <Tab label="AI Insights" />
                  <Tab label="Predictions" disabled={!predictiveAnalysis} />
                </Tabs>

                {/* Data and Chart Tab */}
                <TabPanel value={activeTab} index={0}>
                  {queryResult && (
                    <>
                      {queryResult.chart && !queryResult.chart.error && (
                        <Box sx={{ mb: 3 }}>
                          <Typography variant="h6" gutterBottom>
                            Interactive Chart ({queryResult.chart.chart_type})
                          </Typography>
                          <Plot
                            data={JSON.parse(queryResult.chart.plotly_json).data}
                            layout={{
                              ...JSON.parse(queryResult.chart.plotly_json).layout,
                              autosize: true,
                            }}
                            style={{ width: '100%', height: '400px' }}
                            useResizeHandler
                          />
                        </Box>
                      )}

                      <Typography variant="h6" gutterBottom>
                        Query Results ({queryResult.metadata.row_count} rows)
                      </Typography>
                      <Typography variant="body2" color="text.secondary" gutterBottom>
                        SQL: {queryResult.sql_query}
                      </Typography>
                      
                      <TableContainer component={Paper} sx={{ maxHeight: 400 }}>
                        <Table stickyHeader>
                          <TableHead>
                            <TableRow>
                              {queryResult.metadata.columns.map((column) => (
                                <TableCell key={column}>{column}</TableCell>
                              ))}
                            </TableRow>
                          </TableHead>
                          <TableBody>
                            {queryResult.data.slice(0, 100).map((row, index) => (
                              <TableRow key={index}>
                                {queryResult.metadata.columns.map((column) => (
                                  <TableCell key={column}>
                                    {row[column] !== null ? String(row[column]) : 'NULL'}
                                  </TableCell>
                                ))}
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </TableContainer>
                      
                      {queryResult.data.length > 100 && (
                        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                          Showing first 100 rows of {queryResult.metadata.row_count} total rows
                        </Typography>
                      )}
                    </>
                  )}
                </TabPanel>

                {/* AI Insights Tab */}
                <TabPanel value={activeTab} index={1}>
                  {queryResult && (
                    <Box>
                      <Typography variant="h6" gutterBottom>
                        AI-Generated Insights
                      </Typography>
                      <Paper sx={{ p: 2, bgcolor: 'background.neutral' }}>
                        <Typography variant="body1" style={{ whiteSpace: 'pre-line' }}>
                          {queryResult.insights}
                        </Typography>
                      </Paper>
                    </Box>
                  )}
                </TabPanel>

                {/* Predictions Tab */}
                <TabPanel value={activeTab} index={2}>
                  {predictiveAnalysis && (
                    <Box>
                      <Typography variant="h6" gutterBottom>
                        Predictive Analysis
                      </Typography>
                      
                      <Paper sx={{ p: 2, mb: 3, bgcolor: 'background.neutral' }}>
                        <Typography variant="body1" style={{ whiteSpace: 'pre-line' }}>
                          {predictiveAnalysis.predictions}
                        </Typography>
                      </Paper>

                      {Object.keys(predictiveAnalysis.trends).length > 0 && (
                        <>
                          <Typography variant="h6" gutterBottom>
                            Trend Analysis
                          </Typography>
                          <Grid container spacing={2}>
                            {Object.entries(predictiveAnalysis.trends).map(([column, trend]) => (
                              <Grid item xs={12} sm={6} md={4} key={column}>
                                <Card variant="outlined">
                                  <CardContent>
                                    <Typography variant="subtitle1" gutterBottom>
                                      {column}
                                    </Typography>
                                    <Chip
                                      label={trend.direction}
                                      color={trend.direction === 'increasing' ? 'success' : 'error'}
                                      size="small"
                                      sx={{ mb: 1 }}
                                    />
                                    <Typography variant="body2">
                                      Change: {trend.change_percentage.toFixed(2)}%
                                    </Typography>
                                  </CardContent>
                                </Card>
                              </Grid>
                            ))}
                          </Grid>
                        </>
                      )}
                    </Box>
                  )}
                </TabPanel>
              </CardContent>
            </Card>
          )}
        </Grid>
      </Grid>
    </Box>
  );
};

export default SQLExplorer; 