import asyncio
import json
import re
import os
from typing import Any, Optional
from urllib.parse import quote, urljoin
from datetime import datetime
from pathlib import Path

import sys

# --------- ENHANCED FIX FOR WINDOWS ---------
if sys.platform == 'win32':
    try:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    except Exception as e:
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            pass

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

class EnhancedPhysioNetExtractor:
    """Enhanced intelligent extraction and structuring of PhysioNet dataset metadata"""
    
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
    
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
            
            # Check for existing URL and update if found
            existing_index = None
            for i, d in enumerate(datasets):
                if d.get('Dataset_URL') == metadata.get('Dataset_URL'):
                    existing_index = i
                    break
            
            if existing_index is not None:
                # Update existing entry
                datasets[existing_index] = metadata
                print(f"Updated existing dataset: {metadata.get('Title')}", file=sys.stderr)
                status_msg = {"status": "updated", "message": "Dataset updated in database"}
            else:
                # Add new entry
                datasets.insert(0, metadata)
                print(f"Saved to database: {metadata.get('Title')}", file=sys.stderr)
                status_msg = {"status": "saved", "message": f"Successfully saved. Total datasets: {len(datasets)}"}
            
            with open(DB_FILE, 'w', encoding='utf-8') as f:
                json.dump(datasets, f, indent=2, ensure_ascii=False)
            
            print(f"Total datasets: {len(datasets)}", file=sys.stderr)
            
            status_msg["dataset_count"] = len(datasets)
            return status_msg
            
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
    
    def extract_version_and_doi(self, soup: BeautifulSoup) -> dict:
        """Extract version, DOI, and publication date information"""
        info = {
            "version": "Not specified",
            "published_date": "Not specified",
            "doi_version": "Not specified",
            "doi_latest": "Not specified"
        }
        
        # Look for version info
        version_text = soup.find(string=re.compile(r"Version:?\s*\d+\.\d+\.\d+", re.I))
        if version_text:
            version_match = re.search(r"(\d+\.\d+\.\d+)", str(version_text))
            if version_match:
                info["version"] = version_match.group(1)
        
        # Look for published date
        pub_text = soup.find(string=re.compile(r"Published:?\s*\w+\.?\s+\d+,?\s+\d{4}", re.I))
        if pub_text:
            info["published_date"] = pub_text.strip()
        
        # Extract DOIs
        doi_links = soup.find_all("a", href=re.compile(r"doi\.org"))
        for link in doi_links:
            doi_url = link.get("href", "")
            if "doi.org" in doi_url:
                if "version" in link.get_text().lower():
                    info["doi_version"] = doi_url
                elif "latest" in link.get_text().lower():
                    info["doi_latest"] = doi_url
        
        return info
    
    def extract_authors_and_affiliations(self, soup: BeautifulSoup) -> dict:
        """Extract author information and affiliations"""
        authors = []
        corresponding_author = "Not specified"
        
        # Look for author elements
        author_section = soup.find("div", class_=re.compile(r"author", re.I)) or \
                        soup.find("section", id=re.compile(r"author", re.I))
        
        if author_section:
            author_links = author_section.find_all("a")
            authors = [a.get_text(strip=True) for a in author_links if a.get_text(strip=True)]
        
        # Look for corresponding author
        corr_text = soup.find(string=re.compile(r"Corresponding Author", re.I))
        if corr_text:
            parent = corr_text.find_parent()
            if parent:
                corr_match = re.search(r":\s*([^<\n]+)", parent.get_text())
                if corr_match:
                    corresponding_author = corr_match.group(1).strip()
        
        return {
            "authors": authors if authors else ["Not specified"],
            "corresponding_author": corresponding_author
        }
    
    def extract_file_structure(self, soup: BeautifulSoup) -> dict:
        """Extract information about dataset files and structure"""
        file_info = {
            "total_size_compressed": "Not specified",
            "total_size_uncompressed": "Not specified",
            "file_count": "Not specified",
            "main_folders": []
        }
        
        # Look for size information
        size_text = soup.get_text()
        
        compressed_match = re.search(r"(\d+\.?\d*\s*(?:KB|MB|GB|TB)).*compressed", size_text, re.I)
        if compressed_match:
            file_info["total_size_compressed"] = compressed_match.group(1)
        
        uncompressed_match = re.search(r"(\d+\.?\d*\s*(?:KB|MB|GB|TB)).*uncompressed", size_text, re.I)
        if uncompressed_match:
            file_info["total_size_uncompressed"] = uncompressed_match.group(1)
        
        # Look for file structure information
        file_section = soup.find("section", id="files") or soup.find("div", id="files")
        if file_section:
            folder_items = file_section.find_all("a", href=re.compile(r"/files/"))
            folders = [item.get_text(strip=True) for item in folder_items[:10]]  # Top 10 folders
            file_info["main_folders"] = folders if folders else []
        
        return file_info
    
    def extract_ethics_and_funding(self, soup: BeautifulSoup, page_text: str) -> dict:
        """Extract ethics approval and funding information"""
        ethics_funding = {
            "ethics_approval": "Not specified",
            "irb_number": "Not specified",
            "funding_sources": []
        }
        
        # Look for ethics/IRB information
        ethics_section = soup.find("section", id="ethics") or soup.find("h2", string=re.compile(r"Ethics", re.I))
        if ethics_section:
            ethics_text = ethics_section.find_parent().get_text() if ethics_section.name == "h2" else ethics_section.get_text()
            
            # Extract IRB number
            irb_match = re.search(r"IRB[:\s#]*([A-Z0-9\-]+)", ethics_text, re.I)
            if irb_match:
                ethics_funding["irb_number"] = irb_match.group(1)
            
            # Extract approval text
            approval_match = re.search(r"approved by[^.]+", ethics_text, re.I)
            if approval_match:
                ethics_funding["ethics_approval"] = approval_match.group(0)
        
        # Look for funding information
        funding_keywords = ["NSF", "NIH", "National Science Foundation", "National Institutes of Health", 
                           "funded by", "supported by", "grant"]
        
        for keyword in funding_keywords:
            if keyword.lower() in page_text.lower():
                # Extract grant numbers
                grant_matches = re.findall(r"grant[s]?[:\s#]*([A-Z0-9\-/]+)", page_text, re.I)
                ethics_funding["funding_sources"].extend(grant_matches[:5])
        
        # Remove duplicates
        ethics_funding["funding_sources"] = list(set(ethics_funding["funding_sources"]))
        
        return ethics_funding
    
    def extract_citations_and_references(self, soup: BeautifulSoup) -> dict:
        """Extract citation information and related publications"""
        citations = {
            "primary_citation": "Not specified",
            "related_publications": [],
            "citation_count": "Not specified"
        }
        
        # Look for citation section
        citation_section = soup.find("section", id="citation") or soup.find("div", class_=re.compile(r"citation", re.I))
        if citation_section:
            cite_text = citation_section.get_text()
            citations["primary_citation"] = " ".join(cite_text.split()[:100])
        
        # Look for references section
        refs_section = soup.find("section", id="references") or soup.find("h2", string=re.compile(r"References", re.I))
        if refs_section:
            ref_parent = refs_section.find_parent() if refs_section.name == "h2" else refs_section
            ref_items = ref_parent.find_all("li")[:5]  # First 5 references
            citations["related_publications"] = [item.get_text(strip=True) for item in ref_items]
        
        return citations
    
    def extract_detailed_modalities(self, page_text: str, soup: BeautifulSoup) -> dict:
        """Enhanced modality extraction with detailed information"""
        modality_details = {
            "modalities": [],
            "sensors_used": [],
            "sampling_rates": [],
            "data_formats": []
        }
        
        modality_map = {
            "ECG": ["ecg", "electrocardiogram", "cardiac"],
            "PCG": ["pcg", "phonocardiogram", "heart sound"],
            "EEG": ["eeg", "electroencephalogram", "brain activity"],
            "EMG": ["emg", "electromyogram", "muscle"],
            "PPG": ["ppg", "photoplethysmogram", "pulse"],
            "ACC": ["accelerometer", "acceleration"],
            "Gyroscope": ["gyroscope", "gyro"],
            "Respiratory": ["respiratory", "respiration", "breathing"],
            "Blood Pressure": ["blood pressure", "bp", "arterial pressure"],
            "Temperature": ["temperature", "temp", "thermal"],
            "Skin Conductance": ["skin conductance", "eda", "electrodermal", "gsr"],
            "fNIRS": ["fnirs", "near-infrared spectroscopy", "hemodynamic"],
            "Chest X-ray": ["chest x-ray", "cxr", "radiograph"],
            "CT": ["ct scan", "computed tomography"],
            "MRI": ["mri", "magnetic resonance"],
            "Ultrasound": ["ultrasound", "echocardiogram"],
            "Clinical Notes": ["clinical notes", "discharge", "radiology report", "ehr"],
            "Facial Expression": ["facial expression", "face reader"],
            "Eye Tracking": ["eye tracking", "gaze", "fixation"]
        }
        
        for modality, keywords in modality_map.items():
            if any(kw in page_text.lower() for kw in keywords):
                modality_details["modalities"].append(modality)
        
        # Extract sensor information
        sensor_keywords = ["biopac", "empatica", "nirsport", "facereader", "polar", "fitbit", 
                          "actiheart", "zephyr", "bioharness"]
        for sensor in sensor_keywords:
            if sensor in page_text.lower():
                modality_details["sensors_used"].append(sensor.title())
        
        # Extract sampling rates
        rate_matches = re.findall(r"(\d+\.?\d*)\s*(?:Hz|khz|samples?/s)", page_text, re.I)
        modality_details["sampling_rates"] = list(set(rate_matches[:5]))
        
        # Extract data formats
        format_keywords = ["csv", "mat", "hdf5", "edf", "json", "xml", "dicom", "nifti"]
        for fmt in format_keywords:
            if fmt in page_text.lower():
                modality_details["data_formats"].append(fmt.upper())
        
        return modality_details
    
    def extract_clinical_context(self, page_text: str, soup: BeautifulSoup) -> dict:
        """Extract detailed clinical context and conditions"""
        clinical = {
            "conditions": [],
            "patient_population": "Not specified",
            "inclusion_criteria": "Not specified",
            "exclusion_criteria": "Not specified",
            "clinical_setting": "Not specified"
        }
        
        # Enhanced condition detection
        condition_map = {
            "Arrhythmia": ["arrhythmia", "irregular heartbeat"],
            "Atrial Fibrillation": ["atrial fibrillation", "afib", "af"],
            "Heart Failure": ["heart failure", "chf"],
            "Myocardial Infarction": ["myocardial infarction", "heart attack", "mi"],
            "Sleep Apnea": ["sleep apnea", "osa", "obstructive sleep"],
            "Hypertension": ["hypertension", "high blood pressure"],
            "Pneumonia": ["pneumonia"],
            "COVID-19": ["covid-19", "sars-cov-2", "coronavirus"],
            "COPD": ["copd", "chronic obstructive"],
            "Diabetes": ["diabetes", "diabetic"],
            "Stroke": ["stroke", "cerebrovascular"],
            "Sepsis": ["sepsis", "septic"],
            "Pneumothorax": ["pneumothorax"],
            "Pleural Effusion": ["pleural effusion"],
            "Edema": ["edema", "pulmonary edema"],
            "Cardiomegaly": ["cardiomegaly", "enlarged heart"],
            "Atelectasis": ["atelectasis"],
            "Consolidation": ["consolidation"]
        }
        
        for condition, keywords in condition_map.items():
            if any(kw in page_text.lower() for kw in keywords):
                clinical["conditions"].append(condition)
        
        # Extract population type
        pop_keywords = {
            "ICU patients": ["intensive care", "icu", "critical care"],
            "Emergency department": ["emergency", "ed visits"],
            "Inpatients": ["inpatient", "hospitalized"],
            "Outpatients": ["outpatient", "ambulatory"],
            "Healthy volunteers": ["healthy", "volunteer", "normal subjects"],
            "Neonatal": ["neonatal", "newborn", "infant"],
            "Pediatric": ["pediatric", "children"],
            "Geriatric": ["geriatric", "elderly", "older adults"]
        }
        
        for pop_type, keywords in pop_keywords.items():
            if any(kw in page_text.lower() for kw in keywords):
                clinical["patient_population"] = pop_type
                break
        
        # Extract clinical setting
        setting_keywords = {
            "Hospital": ["hospital", "medical center"],
            "Laboratory": ["laboratory", "lab setting", "controlled environment"],
            "Home": ["home", "ambulatory", "real-world"],
            "Clinic": ["clinic", "outpatient"]
        }
        
        for setting, keywords in setting_keywords.items():
            if any(kw in page_text.lower() for kw in keywords):
                clinical["clinical_setting"] = setting
                break
        
        return clinical
    
    def extract_dataset_characteristics(self, page_text: str, soup: BeautifulSoup) -> dict:
        """Extract comprehensive dataset size and characteristics"""
        characteristics = {
            "num_subjects": "Not specified",
            "num_recordings": "Not specified",
            "duration_per_recording": "Not specified",
            "total_recording_hours": "Not specified",
            "age_range": "Not specified",
            "gender_distribution": "Not specified",
            "data_collection_period": "Not specified"
        }
        
        # Extract number of subjects/patients
        subject_patterns = [
            r"(\d+)\s*(?:subjects?|patients?|participants?|individuals?)",
            r"total\s+(?:of\s+)?(\d+)\s*(?:subjects?|patients?)"
        ]
        
        for pattern in subject_patterns:
            match = re.search(pattern, page_text.lower())
            if match:
                characteristics["num_subjects"] = match.group(1)
                break
        
        # Extract number of recordings/studies
        recording_match = re.search(r"(\d+[\,\d]*)\s*(?:recordings?|studies|exams?)", page_text.lower())
        if recording_match:
            characteristics["num_recordings"] = recording_match.group(1).replace(",", "")
        
        # Extract duration information
        duration_patterns = [
            r"(\d+\.?\d*)\s*(?:hours?|hrs?)\s*(?:per|of|each)",
            r"duration[:\s]+(\d+\.?\d*)\s*(?:minutes?|hours?|days?)"
        ]
        
        for pattern in duration_patterns:
            match = re.search(pattern, page_text.lower())
            if match:
                characteristics["duration_per_recording"] = match.group(0)
                break
        
        # Extract age range
        age_match = re.search(r"age[sd]?[:\s]+(\d+[-–to\s]+\d+)", page_text.lower())
        if age_match:
            characteristics["age_range"] = age_match.group(1)
        
        # Extract gender distribution
        gender_match = re.search(r"(\d+)\s*(?:male|female)", page_text.lower())
        if gender_match:
            characteristics["gender_distribution"] = "Reported"
        
        # Extract data collection period
        period_match = re.search(r"(19|20)\d{2}[-–to\s]+(19|20)\d{2}", page_text)
        if period_match:
            characteristics["data_collection_period"] = period_match.group(0)
        
        return characteristics
    
    def extract_research_applications(self, page_text: str, soup: BeautifulSoup) -> list:
        """Extract potential research applications and use cases"""
        applications = []
        
        application_keywords = {
            "Classification": ["classification", "detection", "diagnosis"],
            "Segmentation": ["segmentation", "localization"],
            "Prediction": ["prediction", "prognosis", "forecasting"],
            "Generation": ["generation", "synthesis", "report generation"],
            "Question Answering": ["question answering", "vqa", "qa"],
            "Summarization": ["summarization", "summarize"],
            "Entity Recognition": ["entity recognition", "ner", "named entity"],
            "Signal Processing": ["signal processing", "filtering", "feature extraction"],
            "Deep Learning": ["deep learning", "neural network", "cnn", "rnn"],
            "Transfer Learning": ["transfer learning", "pre-training"],
            "Explainable AI": ["explainable", "interpretable", "xai"],
            "Multimodal Learning": ["multimodal", "multi-modal", "fusion"],
            "Time Series": ["time series", "temporal", "sequential"],
            "Anomaly Detection": ["anomaly detection", "outlier"]
        }
        
        for app, keywords in application_keywords.items():
            if any(kw in page_text.lower() for kw in keywords):
                applications.append(app)
        
        return applications[:10]  # Limit to top 10
    
    def extract_limitations_and_challenges(self, soup: BeautifulSoup, page_text: str) -> list:
        """Extract dataset limitations and known challenges"""
        limitations = []
        
        # Look for limitations section
        limit_section = soup.find("section", id=re.compile(r"limitation", re.I)) or \
                       soup.find("h2", string=re.compile(r"Limitations?", re.I))
        
        if limit_section:
            limit_parent = limit_section.find_parent() if limit_section.name == "h2" else limit_section
            limit_text = limit_parent.get_text()
            
            # Extract bullet points or sentences
            limit_items = re.split(r'[.\n•]', limit_text)
            limitations = [item.strip() for item in limit_items if len(item.strip()) > 20][:5]
        
        # Look for common limitation patterns
        limitation_patterns = [
            r"small sample size",
            r"limited to.*institution",
            r"no control group",
            r"imbalanced",
            r"single center",
            r"retrospective"
        ]
        
        for pattern in limitation_patterns:
            if re.search(pattern, page_text.lower()):
                match = re.search(f"[^.]*{pattern}[^.]*", page_text.lower(), re.I)
                if match:
                    limitations.append(match.group(0).strip())
        
        return list(set(limitations))[:5]  # Top 5 unique limitations
    
    def extract_access_requirements(self, soup: BeautifulSoup, page_text: str) -> dict:
        """Extract information about data access requirements"""
        access = {
            "access_type": "Not specified",
            "license": "Not specified",
            "training_required": False,
            "dua_required": False,
            "credentialing_required": False
        }
        
        # Determine access type
        if "open access" in page_text.lower():
            access["access_type"] = "Open Access"
        elif "credentialed" in page_text.lower() or "restricted" in page_text.lower():
            access["access_type"] = "Credentialed/Restricted"
        elif "request" in page_text.lower():
            access["access_type"] = "Request Required"
        
        # Extract license
        license_section = soup.find("a", href=re.compile(r"license", re.I))
        if license_section:
            access["license"] = license_section.get_text(strip=True)
        
        # Check requirements
        if "citi" in page_text.lower() or "training" in page_text.lower():
            access["training_required"] = True
        
        if "dua" in page_text.lower() or "data use agreement" in page_text.lower():
            access["dua_required"] = True
        
        if "credential" in page_text.lower():
            access["credentialing_required"] = True
        
        return access
    
    async def extract_metadata(self, url: str) -> dict:
        """Enhanced metadata extraction with comprehensive intelligence"""
        try:
            print(f"Fetching URL: {url}", file=sys.stderr)
            response = await self.client.get(url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            page_text = soup.get_text()
            
            # Initialize comprehensive metadata structure
            metadata = {
                # Basic Information
                "Title": "Not specified",
                "Year": "Not specified",
                "Version": "Not specified",
                "Published_Date": "Not specified",
                "DOI_Version": "Not specified",
                "DOI_Latest": "Not specified",
                
                # Description
                "Description": "Not specified",
                "Abstract_Full": "Not specified",
                
                # Authors and Contributors
                "Authors": [],
                "Corresponding_Author": "Not specified",
                
                # Physiological/Imaging Modalities
                "Physiological_Modality": "Not specified",
                "Modalities_List": [],
                "Sensors_Used": [],
                "Sampling_Rates": [],
                "Data_Formats": [],
                
                # Clinical Context
                "Clinical_Condition": "Not specified",
                "Conditions_List": [],
                "Patient_Population": "Not specified",
                "Clinical_Setting": "Not specified",
                
                # Dataset Characteristics
                "Dataset_Size": "Not specified",
                "Number_of_Subjects": "Not specified",
                "Number_of_Recordings": "Not specified",
                "Duration_Per_Recording": "Not specified",
                "Age_Range": "Not specified",
                "Gender_Distribution": "Not specified",
                "Data_Collection_Period": "Not specified",
                
                # File Information
                "Total_Size_Compressed": "Not specified",
                "Total_Size_Uncompressed": "Not specified",
                "Main_Folders": [],
                
                # Research Context
                "Target_Research_Task": "Not specified",
                "Research_Applications": [],
                "Parent_Project": "Not specified",
                "Funding_Sources": [],
                
                # Quality and Ethics
                "Ethics_Approval": "Not specified",
                "IRB_Number": "Not specified",
                "Limitations": [],
                "Data_Quality_Notes": "Not specified",
                
                # Access Information
                "Access_Type": "Not specified",
                "Licensing_or_Availability": "Not specified",
                "Training_Required": False,
                "DUA_Required": False,
                "Credentialing_Required": False,
                
                # Citations
                "Primary_Citation": "Not specified",
                "Related_Publications": [],
                
                # Keywords and Metadata
                "Keywords_Used": [],
                "Metadata_Completeness": "Not specified",
                
                # URL
                "Dataset_URL": url
            }
            
            # Extract title
            title_elem = soup.find("h1")
            if title_elem:
                metadata["Title"] = title_elem.get_text(strip=True)
            
            # Extract version and DOI information
            version_info = self.extract_version_and_doi(soup)
            metadata["Version"] = version_info["version"]
            metadata["Published_Date"] = version_info["published_date"]
            metadata["DOI_Version"] = version_info["doi_version"]
            metadata["DOI_Latest"] = version_info["doi_latest"]
            
            # Extract year from published date
            if metadata["Published_Date"] != "Not specified":
                year_match = re.search(r"(19|20)\d{2}", metadata["Published_Date"])
                if year_match:
                    metadata["Year"] = year_match.group(0)
            
            # Extract authors
            author_info = self.extract_authors_and_affiliations(soup)
            metadata["Authors"] = author_info["authors"]
            metadata["Corresponding_Author"] = author_info["corresponding_author"]
            
            # Extract abstract/description
            abstract = soup.find("div", {"id": "abstract"}) or soup.find("section", {"id": "abstract"})
            if abstract:
                desc_text = abstract.get_text(strip=True)
                metadata["Abstract_Full"] = desc_text
                metadata["Description"] = " ".join(desc_text.split()[:150])  # First 150 words
            
            # Extract detailed modalities
            modality_info = self.extract_detailed_modalities(page_text, soup)
            metadata["Modalities_List"] = modality_info["modalities"]
            metadata["Physiological_Modality"] = ", ".join(modality_info["modalities"]) if modality_info["modalities"] else "Not specified"
            metadata["Sensors_Used"] = modality_info["sensors_used"]
            metadata["Sampling_Rates"] = modality_info["sampling_rates"]
            metadata["Data_Formats"] = modality_info["data_formats"]
            
            # Extract clinical context
            clinical_info = self.extract_clinical_context(page_text, soup)
            metadata["Conditions_List"] = clinical_info["conditions"]
            metadata["Clinical_Condition"] = ", ".join(clinical_info["conditions"]) if clinical_info["conditions"] else "General healthy + mixed conditions"
            metadata["Patient_Population"] = clinical_info["patient_population"]
            metadata["Clinical_Setting"] = clinical_info["clinical_setting"]
            
            # Extract dataset characteristics
            characteristics = self.extract_dataset_characteristics(page_text, soup)
            metadata["Number_of_Subjects"] = characteristics["num_subjects"]
            metadata["Number_of_Recordings"] = characteristics["num_recordings"]
            metadata["Duration_Per_Recording"] = characteristics["duration_per_recording"]
            metadata["Age_Range"] = characteristics["age_range"]
            metadata["Gender_Distribution"] = characteristics["gender_distribution"]