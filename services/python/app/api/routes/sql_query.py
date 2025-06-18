# SQL Query API for LLM-guided relational data exploration
import asyncio
import json
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dependency_injector.wiring import inject
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.modules.retrieval.retrieval_service import RetrievalService
from app.setups.query_setup import AppContainer

router = APIRouter()

class SQLQueryRequest(BaseModel):
    query: str
    database_connection: str
    natural_language_query: str
    chart_type: Optional[str] = "auto"
    limit: Optional[int] = 1000

class ChartGenerationRequest(BaseModel):
    data: List[Dict[str, Any]]
    chart_type: str
    title: Optional[str] = None
    x_column: Optional[str] = None
    y_column: Optional[str] = None

@router.post("/execute-sql")
@inject
async def execute_sql_with_llm_guidance(
    request: Request,
    query_info: SQLQueryRequest,
    retrieval_service: RetrievalService = Depends(lambda: request.app.container.retrieval_service()),
):
    """Execute SQL query with LLM guidance and generate interactive charts"""
    try:
        container = request.app.container
        logger = container.logger()
        
        # Get LLM instance for query analysis
        llm = await retrieval_service.get_llm_instance()
        if llm is None:
            raise HTTPException(
                status_code=500,
                detail="Failed to initialize LLM service for SQL analysis."
            )

        # Analyze the natural language query to generate SQL
        if not query_info.query and query_info.natural_language_query:
            sql_generation_prompt = f"""
            Convert the following natural language query to SQL:
            "{query_info.natural_language_query}"
            
            Please provide only the SQL query without any explanation.
            Ensure the query is safe and follows best practices.
            """
            
            response = await llm.ainvoke([{"role": "user", "content": sql_generation_prompt}])
            generated_sql = response.content.strip()
            
            # Clean up the SQL (remove markdown formatting if present)
            if generated_sql.startswith("```sql"):
                generated_sql = generated_sql.replace("```sql", "").replace("```", "").strip()
            
            query_info.query = generated_sql

        # Execute SQL query
        try:
            engine = create_engine(query_info.database_connection)
            with engine.connect() as connection:
                result = connection.execute(text(query_info.query))
                
                # Convert to pandas DataFrame for easier manipulation
                df = pd.DataFrame(result.fetchall(), columns=result.keys())
                
                if len(df) > query_info.limit:
                    df = df.head(query_info.limit)
                
                # Convert DataFrame to dict for JSON serialization
                data = df.to_dict('records')
                
        except SQLAlchemyError as e:
            logger.error(f"SQL execution error: {str(e)}")
            raise HTTPException(status_code=400, detail=f"SQL execution failed: {str(e)}")

        # Generate chart recommendations using LLM
        if query_info.chart_type == "auto" and data:
            chart_recommendation_prompt = f"""
            Based on this SQL query result data structure, recommend the best chart type:
            
            Columns: {list(df.columns)}
            Data types: {df.dtypes.to_dict()}
            Sample data: {data[:3] if len(data) > 3 else data}
            
            Respond with one of: bar, line, scatter, pie, histogram, box, area
            Only respond with the chart type name.
            """
            
            response = await llm.ainvoke([{"role": "user", "content": chart_recommendation_prompt}])
            recommended_chart = response.content.strip().lower()
            query_info.chart_type = recommended_chart

        # Generate interactive chart
        chart_data = None
        if data and query_info.chart_type != "none":
            chart_data = await generate_interactive_chart(
                data, query_info.chart_type, df.columns.tolist()
            )

        # Generate insights using LLM
        insights_prompt = f"""
        Analyze this SQL query result and provide key insights:
        
        Query: {query_info.query}
        Data summary: {df.describe().to_dict() if not df.empty else "No data"}
        Row count: {len(df)}
        
        Provide 3-5 key insights in bullet points.
        """
        
        response = await llm.ainvoke([{"role": "user", "content": insights_prompt}])
        insights = response.content.strip()

        return {
            "sql_query": query_info.query,
            "data": data,
            "chart": chart_data,
            "insights": insights,
            "metadata": {
                "row_count": len(df),
                "columns": list(df.columns),
                "chart_type": query_info.chart_type
            }
        }

    except Exception as e:
        logger.error(f"Error in SQL query execution: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))


async def generate_interactive_chart(data: List[Dict], chart_type: str, columns: List[str]) -> Dict:
    """Generate interactive Plotly chart data"""
    try:
        df = pd.DataFrame(data)
        
        # Auto-detect x and y columns
        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
        categorical_cols = df.select_dtypes(include=['object', 'category']).columns.tolist()
        
        x_col = categorical_cols[0] if categorical_cols else columns[0]
        y_col = numeric_cols[0] if numeric_cols else columns[1] if len(columns) > 1 else columns[0]
        
        # Generate chart based on type
        if chart_type == "bar":
            fig = px.bar(df, x=x_col, y=y_col, title=f"{y_col} by {x_col}")
        elif chart_type == "line":
            fig = px.line(df, x=x_col, y=y_col, title=f"{y_col} over {x_col}")
        elif chart_type == "scatter":
            fig = px.scatter(df, x=x_col, y=y_col, title=f"{y_col} vs {x_col}")
        elif chart_type == "pie":
            if len(categorical_cols) > 0 and len(numeric_cols) > 0:
                fig = px.pie(df, names=x_col, values=y_col, title=f"Distribution of {y_col}")
            else:
                # Fallback to value counts
                value_counts = df[x_col].value_counts()
                fig = px.pie(values=value_counts.values, names=value_counts.index, 
                           title=f"Distribution of {x_col}")
        elif chart_type == "histogram":
            fig = px.histogram(df, x=y_col, title=f"Distribution of {y_col}")
        elif chart_type == "box":
            fig = px.box(df, y=y_col, title=f"Box plot of {y_col}")
        else:  # Default to bar
            fig = px.bar(df, x=x_col, y=y_col, title=f"{y_col} by {x_col}")
        
        # Convert to JSON for frontend
        return {
            "plotly_json": fig.to_json(),
            "chart_type": chart_type,
            "x_column": x_col,
            "y_column": y_col
        }
        
    except Exception as e:
        return {
            "error": f"Chart generation failed: {str(e)}",
            "chart_type": chart_type
        }


@router.post("/generate-predictive-analysis")
@inject
async def generate_predictive_analysis(
    request: Request,
    query_info: SQLQueryRequest,
    retrieval_service: RetrievalService = Depends(lambda: request.app.container.retrieval_service()),
):
    """Generate predictive analysis from SQL data"""
    try:
        container = request.app.container
        logger = container.logger()
        
        # Get LLM instance
        llm = await retrieval_service.get_llm_instance()
        if llm is None:
            raise HTTPException(
                status_code=500,
                detail="Failed to initialize LLM service."
            )

        # Execute the SQL query first
        engine = create_engine(query_info.database_connection)
        with engine.connect() as connection:
            result = connection.execute(text(query_info.query))
            df = pd.DataFrame(result.fetchall(), columns=result.keys())

        # Generate predictive insights using LLM
        prediction_prompt = f"""
        Based on this dataset, provide predictive analysis and trends:
        
        Data summary:
        - Columns: {list(df.columns)}
        - Data types: {df.dtypes.to_dict()}
        - Statistical summary: {df.describe().to_dict()}
        - Sample data: {df.head().to_dict('records')}
        
        Please provide:
        1. Trend analysis
        2. Potential future predictions
        3. Key patterns identified
        4. Recommended actions
        
        Format your response as structured insights.
        """
        
        response = await llm.ainvoke([{"role": "user", "content": prediction_prompt}])
        predictions = response.content.strip()

        # Simple trend calculation for numeric columns
        trends = {}
        for col in df.select_dtypes(include=['number']).columns:
            if len(df) > 1:
                trend_direction = "increasing" if df[col].iloc[-1] > df[col].iloc[0] else "decreasing"
                trends[col] = {
                    "direction": trend_direction,
                    "change_percentage": ((df[col].iloc[-1] - df[col].iloc[0]) / df[col].iloc[0] * 100) if df[col].iloc[0] != 0 else 0
                }

        return {
            "predictions": predictions,
            "trends": trends,
            "data_summary": {
                "row_count": len(df),
                "columns": list(df.columns),
                "numeric_columns": df.select_dtypes(include=['number']).columns.tolist()
            }
        }

    except Exception as e:
        logger.error(f"Error in predictive analysis: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e)) 