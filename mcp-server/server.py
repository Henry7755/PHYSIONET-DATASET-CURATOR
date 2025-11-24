import asyncio
import json
import re
import os
from typing import Any
from urllib.parse import quote
from datetime import datetime
from pathlib import Path

import sys

# --------- ENHANCED FIX FOR WINDOWS ---------
# Forces UTF-8 encoding so print() NEVER crashes
if sys.platform == 'win32':
    try:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    except Exception as e:
        # Fallback: if reconfigure is available
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            pass
# ---------------------------------------------

import httpx
from bs4 import BeautifulSoup
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Initialize MCP server
app = Server("physionet-intelligence-server")

# Database file path
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DB_FILE = PROJECT_ROOT / "web-app" / "public" / "curated_datasets.json"

# Ensure output folder exists
DB_FILE.parent.mkdir(parents=True, exist_ok=True)

PHYSIONET_BASE = "https://physionet.org"

class PhysioNetExtractor:
    """Extract and structure PhysioNet dataset metadata"""
    
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    
    async def close(self):
        await self.client.aclose()
    
    def load_database(self) -> list[dict]:
        if DB_FILE.exists():
            try:
                with open(DB_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading database: {e}", file=sys.stderr)
                return []
        return []
    
    def save_to_database(self, metadata: dict) -> dict:
        try:
            datasets = self.load_database()
            metadata['id'] = int(datetime.now().timestamp() * 1000)
            metadata['curated_date'] = datetime.now().isoformat()
            
            existing_urls = [d.get('Dataset_URL') for d in datasets]
            if metadata.get('Dataset_URL') in existing_urls:
                print(f"Dataset already exists: {metadata.get('Title')}", file=sys.stderr)
                return {"status": "exists", "message": "Dataset already in database"}

            datasets.insert(0, metadata)
            
            with open(DB_FILE, 'w', encoding='utf-8') as f:
                json.dump(datasets, f, indent=2, ensure_ascii=False)
            
            print(f"Saved to database: {metadata.get('Title')}", file=sys.stderr)
            print(f"Total datasets: {len(datasets)}", file=sys.stderr)
            
            return {
                "status": "saved",
                "message": f"Successfully saved. Total datasets: {len(datasets)}",
                "dataset_count": len(datasets)
            }
            
        except Exception as e:
            print(f"Error saving to database: {e}", file=sys.stderr)
            return {"status": "error", "message": str(e)}
    
    async def search_dataset(self, query: str) -> list[dict]:
        if query.startswith("http"):
            return [{"title": "Direct URL", "url": query}]
        
        search_url = f"{PHYSIONET_BASE}/search/?q={quote(query)}&t=content"
        try:
            response = await self.client.get(search_url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            results = []
            
            for link in soup.find_all("a", href=re.compile(r"/content/[^/]+/[^/]+")):
                href = link.get("href")
                if href and "/content/" in href:
                    full_url = f"{PHYSIONET_BASE}{href}" if href.startswith("/") else href
                    title = link.get_text(strip=True)
                    if title and full_url not in [r["url"] for r in results]:
                        results.append({"title": title, "url": full_url})
            
            return results[:5]
            
        except Exception as e:
            return [{"error": f"Search failed: {str(e)}"}]
    
    async def extract_metadata(self, url: str) -> dict:
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            metadata = {
                "Title": "Not specified",
                "Year": "Not specified",
                "Description": "Not specified",
                "Physiological_Modality": "Not specified",
                "Clinical_Condition": "Not specified",
                "Environment_or_Acquisition_Setting": "Not specified",
                "Target_Research_Task": "Not specified",
                "Metadata_Completeness": "Not specified",
                "Dataset_Size": "Not specified",
                "Population_Type": "Not specified",
                "Licensing_or_Availability": "Not specified",
                "Keywords_Used": [],
                "Parent_Project": "Not specified",
                "Limitations": "Not specified",
                "Dataset_URL": url
            }
            
            title_elem = soup.find("h1")
            if title_elem:
                metadata["Title"] = title_elem.get_text(strip=True)
            
            version_elem = soup.find(string=re.compile(r"Version|Published|Released"))
            if version_elem:
                year_match = re.search(r"(19|20)\d{2}", str(version_elem))
                if year_match:
                    metadata["Year"] = year_match.group(0)
            
            abstract = soup.find("div", {"id": "abstract"}) or soup.find("section", {"id": "abstract"})
            if abstract:
                desc_text = abstract.get_text(strip=True)
                metadata["Description"] = " ".join(desc_text.split()[:100])
            
            page_text = soup.get_text().lower()
            
            modalities = []
            modality_keywords = {
                "ECG": ["ecg", "electrocardiogram"],
                "PCG": ["pcg", "phonocardiogram", "heart sound"],
                "EEG": ["eeg", "electroencephalogram"],
                "EMG": ["emg", "electromyogram"],
                "PPG": ["ppg", "photoplethysmogram"],
                "ACC": ["accelerometer"],
                "Respiratory": ["respiratory", "respiration"],
                "Blood Pressure": ["blood pressure", "bp"],
                "Imaging": ["mri", "ct scan", "x-ray", "cbct"],
                "Clinical Notes": ["clinical notes", "discharge"],
            }
            
            for modality, keywords in modality_keywords.items():
                if any(kw in page_text for kw in keywords):
                    modalities.append(modality)
            
            metadata["Physiological_Modality"] = ", ".join(modalities) if modalities else "Not specified"
            
            conditions = []
            condition_keywords = {
                "Arrhythmia": ["arrhythmia"],
                "Atrial Fibrillation": ["atrial fibrillation", "afib"],
                "Heart Failure": ["heart failure"],
                "Sleep Apnea": ["sleep apnea"],
                "Hypertension": ["hypertension"],
                "Pneumonia": ["pneumonia"],
                "COVID-19": ["covid-19", "sars-cov-2"],
            }
            
            for condition, keywords in condition_keywords.items():
                if any(kw in page_text for kw in keywords):
                    conditions.append(condition)
            
            metadata["Clinical_Condition"] = ", ".join(conditions) if conditions else "General healthy + mixed conditions"
            
            size_info = []
            subject_match = re.search(r"(\d+)\s*(?:subjects?|patients?)", page_text)
            if subject_match:
                size_info.append(f"{subject_match.group(1)} subjects")
            
            duration_match = re.search(r"(\d+)\s*(?:hours?|days?)", page_text)
            if duration_match:
                size_info.append(duration_match.group(0))
            
            metadata["Dataset_Size"] = ", ".join(size_info) if size_info else "Not specified"
            
            filled_fields = sum(1 for v in metadata.values() if v != "Not specified" and v != [])
            completeness_ratio = filled_fields / len(metadata)
            
            if completeness_ratio > 0.7:
                metadata["Metadata_Completeness"] = "High"
            elif completeness_ratio > 0.4:
                metadata["Metadata_Completeness"] = "Moderate"
            else:
                metadata["Metadata_Completeness"] = "Low"
            
            return metadata
            
        except Exception as e:
            return {"error": f"Failed to extract metadata: {str(e)}"}

extractor = PhysioNetExtractor()

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_physionet",
            description="Search for PhysioNet datasets",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_dataset_metadata",
            description="Extract metadata from PhysioNet dataset URL",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"}
                },
                "required": ["url"]
            }
        ),
        Tool(
            name="curate_and_save_dataset",
            description="Fetch, analyze, and save dataset",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"}
                },
                "required": ["url"]
            }
        ),
        Tool(
            name="batch_curate_datasets",
            description="Curate multiple datasets",
            inputSchema={
                "type": "object",
                "properties": {
                    "urls": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["urls"]
            }
        ),
        Tool(
            name="get_database_stats",
            description="Get statistics about curated datasets",
            inputSchema={"type": "object", "properties": {}}
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    if name == "search_physionet":
        query = arguments.get("query", "")
        results = await extractor.search_dataset(query)
        return [TextContent(type="text", text=json.dumps(results, indent=2))]
    
    elif name == "get_dataset_metadata":
        url = arguments.get("url", "")
        metadata = await extractor.extract_metadata(url)
        return [TextContent(type="text", text=json.dumps(metadata, indent=2))]
    
    elif name == "curate_and_save_dataset":
        url = arguments.get("url", "")
        print(f"Curating: {url}", file=sys.stderr)
        
        metadata = await extractor.extract_metadata(url)
        if "error" in metadata:
            return [TextContent(type="text", text=json.dumps(metadata, indent=2))]
        
        save_result = extractor.save_to_database(metadata)
        
        result = {"metadata": metadata, "save_result": save_result}
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "batch_curate_datasets":
        urls = arguments.get("urls", [])
        results = []
        
        print(f"Batch curating {len(urls)} datasets...", file=sys.stderr)
        
        for i, url in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] Processing: {url}", file=sys.stderr)
            
            metadata = await extractor.extract_metadata(url)
            if "error" not in metadata:
                save_result = extractor.save_to_database(metadata)
                results.append({
                    "url": url,
                    "title": metadata.get("Title"),
                    "status": save_result.get("status")
                })
            else:
                results.append({
                    "url": url,
                    "status": "error",
                    "error": metadata.get("error")
                })
            
            await asyncio.sleep(2)
        
        summary = {
            "total": len(urls),
            "successful": len([r for r in results if r["status"] == "saved"]),
            "already_exists": len([r for r in results if r["status"] == "exists"]),
            "failed": len([r for r in results if r["status"] == "error"]),
            "results": results
        }
        
        return [TextContent(type="text", text=json.dumps(summary, indent=2))]
    
    elif name == "get_database_stats":
        datasets = extractor.load_database()
        stats = {
            "total_datasets": len(datasets),
            "recent_datasets": [
                {
                    "title": d.get("Title"),
                    "year": d.get("Year"),
                    "curated_date": d.get("curated_date")
                }
                for d in datasets[:5]
            ]
        }
        return [TextContent(type="text", text=json.dumps(stats, indent=2))]
    
    return [TextContent(type="text", text=json.dumps({"error": "Unknown tool"}))]

async def main():
    # Use stderr for all logging in MCP servers (stdout is reserved for MCP protocol)
    print(f"Database file: {DB_FILE}", file=sys.stderr)
    print("PhysioNet MCP Server starting...", file=sys.stderr)
    
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())