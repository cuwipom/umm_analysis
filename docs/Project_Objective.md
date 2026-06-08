# **Project Charter: Hairfall Insights Text Analytics**

## **1\. Executive Summary**

The goal of this project is to convert a highly unstructured, conversational dataset of approximately 10k tweets (scraped via the Scweet library) into a structured, highly queryable relational and vector database.

By employing a modern **ELT (Extract, Load, Transform)** pipeline powered by Large Language Models (LLMs) and advanced natural language processing (NLP), this project aims to uncover rich consumer insights regarding hair loss, user sentiments, product concerns, and underlying physical or emotional causes without incurring repetitive LLM API costs.

## **2\. Core Objectives**

### **A. Structured Semantic Enrichment**

* **Challenge:** Social media text is messy, filled with emojis, typos, slang, and context-dependent phrases that traditional keyword searches fail to capture.  
* **Objective:** Use LLM "JSON Mode" and structural validation (Pydantic) to parse and enrich each raw tweet with standardized fields (such as Sentiment, Broad Category, and Specific Sub-Cause) on a single pass.

### **B. Scalable, Cost-Effective Architecture**

* **Challenge:** Using LLMs as search or query engines directly over large datasets is slow, expensive, and non-deterministic.  
* **Objective:** Decouple the "parsing/understanding" stage from the "analysis" stage. By transforming the unstructured data once and storing it in a structured relational database, future analyses can be executed instantly and for free using standard SQL queries (GROUP BY, COUNT, AVG).

### **C. Discovery of "Unknown Unknowns" (The Hybrid Layer)**

* **Challenge:** Rigid database schemas can prevent analysts from finding emerging trends or issues they didn't anticipate when designing the initial categories.  
* **Objective:** Generate and integrate **vector embeddings** right alongside standard SQL data. This enables semantic search (searching by concept rather than exact keywords) and cluster analysis (e.g., using algorithms like K-Means to group similar complaints naturally and discover new, unpredicted trends).

## **3\. High-Level Questions This Project Will Answer**

Through this architecture, the data analytics layer will easily solve complex questions such as:

1. **What is the emotional baseline?** What percentage of hairfall discussions are driven by severe distress/anxiety vs. casual product discovery?  
2. **What are the primary triggers?** Can we segment hairfall triggers (e.g., water quality, post-pregnancy, academic stress, chemical damage from products) cleanly across thousands of discussions?  
3. **Are there emerging remedies?** What natural treatments, brands, or routines are organically gaining traction in positive sentiment clusters?  
4. **Are there product-specific complaints?** Is there a sudden spike in negative sentiment correlated to a specific ingredient, product type, or brand name?

## **4\. Key Success Metrics**

* **Pipeline Reproducibility:** Structuring text systematically using strict schema validation, ensuring consistent database writes.  
* **Insight Discovery Rate:** Successfully mapping both predefined closed categories (SQL Enums) and open-ended micro-insights (SQL Text \+ Embeddings).  
* **Analysis Latency:** Reducing query times from minutes (LLM prompt-reading) to milliseconds (standard SQL execution).  
* **Resource & Cost Efficiency:** Minimizing token usage by utilizing cheap "mini/flash" models in batch modes for extraction.