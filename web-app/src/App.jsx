import React, { useState, useEffect } from 'react';
import { RefreshCw, Download, Copy, Database, Trash2, FileText, CheckCircle, ExternalLink } from 'lucide-react';

export default function IntegratedPhysioNetCurator() {
  const [curatedDatasets, setCuratedDatasets] = useState([]);
  const [loading, setLoading] = useState(false);
  const [copySuccess, setCopySuccess] = useState('');
  const [lastRefresh, setLastRefresh] = useState(null);

  // Load datasets from the JSON file created by MCP server
  const loadDatasets = async () => {
    setLoading(true);
    try {
      const response = await fetch('/curated_datasets.json');
      if (response.ok) {
        const data = await response.json();
        setCuratedDatasets(data);
        setLastRefresh(new Date());
        console.log(`✅ Loaded ${data.length} datasets`);
      } else {
        console.log('No datasets file found yet');
        setCuratedDatasets([]);
      }
    } catch (error) {
      console.error('Error loading datasets:', error);
      // Fallback to localStorage
      const saved = localStorage.getItem('physionet_curated');
      if (saved) {
        setCuratedDatasets(JSON.parse(saved));
      }
    } finally {
      setLoading(false);
    }
  };

  // Auto-load on mount
  useEffect(() => {
    loadDatasets();
  }, []);

  // Auto-refresh every 10 seconds when Claude is curating
  useEffect(() => {
    const interval = setInterval(loadDatasets, 10000);
    return () => clearInterval(interval);
  }, []);

  const deleteDataset = (id) => {
    if (window.confirm('Are you sure you want to delete this dataset?')) {
      const updated = curatedDatasets.filter(d => d.id !== id);
      setCuratedDatasets(updated);
      // Note: This only removes from view, not from the MCP database file
      alert('Note: Dataset removed from view. To permanently delete, remove from curated_datasets.json');
    }
  };

  const exportAllData = (format) => {
    if (curatedDatasets.length === 0) return;

    if (format === 'json') {
      const jsonStr = JSON.stringify(curatedDatasets, null, 2);
      downloadFile(jsonStr, 'application/json', 'physionet_curated.json');
    } else if (format === 'csv') {
      const headers = [
        'Title', 'Year', 'Description', 'Physiological_Modality', 
        'Clinical_Condition', 'Environment_or_Acquisition_Setting', 
        'Target_Research_Task', 'Metadata_Completeness', 'Dataset_Size',
        'Population_Type', 'Licensing_or_Availability', 'Keywords_Used',
        'Parent_Project', 'Limitations', 'Dataset_URL'
      ];
      
      const csvRows = [headers.join(',')];
      
      curatedDatasets.forEach(dataset => {
        const row = headers.map(header => {
          let value = dataset[header] || '';
          if (Array.isArray(value)) {
            value = value.join('; ');
          }
          value = String(value).replace(/"/g, '""');
          if (value.includes(',') || value.includes('\n')) {
            value = `"${value}"`;
          }
          return value;
        });
        csvRows.push(row.join(','));
      });
      
      downloadFile(csvRows.join('\n'), 'text/csv', 'physionet_curated.csv');
    } else if (format === 'markdown') {
      let markdown = `# PhysioNet Curated Datasets\n\n`;
      markdown += `Generated: ${new Date().toLocaleString()}\n`;
      markdown += `Total Datasets: ${curatedDatasets.length}\n\n---\n\n`;
      
      curatedDatasets.forEach((dataset, index) => {
        markdown += `# Dataset ${index + 1}: ${dataset.Title}\n\n`;
        markdown += `**Title:** [${dataset.Title}](${dataset.Dataset_URL || 'https://physionet.org'})\n`;
        markdown += `**Year:** ${dataset.Year}\n`;
        markdown += `**Description:** ${dataset.Description}\n`;
        markdown += `**Physiological Modality:** ${dataset.Physiological_Modality}\n`;
        markdown += `**Clinical Condition:** ${dataset.Clinical_Condition}\n`;
        markdown += `**Environment/Acquisition setting:** ${dataset.Environment_or_Acquisition_Setting}\n`;
        markdown += `**Target Research Task:** ${dataset.Target_Research_Task}\n`;
        markdown += `**Metadata Completeness:** ${dataset.Metadata_Completeness}\n`;
        markdown += `**Dataset Size:** ${dataset.Dataset_Size}\n`;
        markdown += `**Population type:** ${dataset.Population_Type}\n`;
        markdown += `**Licensing/Availability:** ${dataset.Licensing_or_Availability}\n`;
        markdown += `**Keywords used:** ${Array.isArray(dataset.Keywords_Used) ? dataset.Keywords_Used.join(', ') : dataset.Keywords_Used}\n`;
        markdown += `**Parent Project:** ${dataset.Parent_Project}\n`;
        markdown += `**Limitations:** ${dataset.Limitations}\n\n---\n\n`;
      });
      
      downloadFile(markdown, 'text/markdown', 'physionet_curated.md');
    }
  };

  const downloadFile = (content, type, filename) => {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopySuccess('Copied!');
      setTimeout(() => setCopySuccess(''), 2000);
    });
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-indigo-50 p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-4xl font-bold text-gray-900 mb-2">
            PhysioNet Dataset Curator
          </h1>
          <p className="text-gray-600">
            Auto-synced with Claude Desktop MCP Server
          </p>
          <div className="mt-2 text-sm text-gray-500">
            {curatedDatasets.length} dataset{curatedDatasets.length !== 1 ? 's' : ''} curated
            {lastRefresh && ` • Last updated: ${lastRefresh.toLocaleTimeString()}`}
          </div>
        </div>

        {/* Instructions Box */}
        <div className="bg-gradient-to-r from-blue-50 to-indigo-50 border-2 border-blue-200 rounded-lg p-6 mb-6">
          <h3 className="font-bold text-blue-900 mb-3 text-lg">🤖 Autonomous Curation with Claude Desktop:</h3>
          <ol className="text-sm text-blue-800 space-y-2 list-decimal list-inside">
            <li className="font-semibold">Open Claude Desktop and say:
              <div className="mt-2 bg-white p-3 rounded border border-blue-200 font-mono text-xs">
                "Curate these PhysioNet datasets and save them to the database:<br/>
                1. https://physionet.org/content/mitdb/1.0.0/<br/>
                2. https://physionet.org/content/mimiciv/3.1/<br/>
                [add more URLs...]"
              </div>
            </li>
            <li>Claude will automatically use the MCP server to fetch and save each dataset</li>
            <li>This web app auto-refreshes every 10 seconds to show new datasets</li>
            <li>Watch the datasets appear here in real-time!</li>
            <li>Export everything when done</li>
          </ol>
        </div>

        {/* Refresh Button */}
        <div className="bg-white rounded-lg shadow-md p-4 mb-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Database className="w-5 h-5 text-blue-600" />
            <span className="text-gray-700 font-medium">
              Auto-refresh active • Synced with MCP database
            </span>
          </div>
          <button
            onClick={loadDatasets}
            disabled={loading}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 flex items-center gap-2 transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh Now
          </button>
        </div>

        {/* Export Controls */}
        {curatedDatasets.length > 0 && (
          <div className="bg-white rounded-lg shadow-md p-6 mb-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Database className="w-5 h-5 text-green-600" />
                <h2 className="text-lg font-semibold text-gray-900">
                  Export Curated Data
                </h2>
              </div>
            </div>
            
            <div className="flex flex-wrap gap-3">
              <button
                onClick={() => exportAllData('json')}
                className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 flex items-center gap-2 transition-colors"
              >
                <Download className="w-4 h-4" />
                Export JSON ({curatedDatasets.length})
              </button>
              <button
                onClick={() => exportAllData('csv')}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center gap-2 transition-colors"
              >
                <Download className="w-4 h-4" />
                Export CSV
              </button>
              <button
                onClick={() => exportAllData('markdown')}
                className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 flex items-center gap-2 transition-colors"
              >
                <FileText className="w-4 h-4" />
                Export Markdown
              </button>
              <button
                onClick={() => copyToClipboard(JSON.stringify(curatedDatasets, null, 2))}
                className="px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700 flex items-center gap-2 transition-colors"
              >
                <Copy className="w-4 h-4" />
                {copySuccess || 'Copy JSON'}
              </button>
            </div>
          </div>
        )}

        {/* Loading State */}
        {loading && curatedDatasets.length === 0 && (
          <div className="bg-white rounded-lg shadow-md p-12 text-center">
            <RefreshCw className="w-12 h-12 text-blue-600 animate-spin mx-auto mb-4" />
            <p className="text-gray-600">Loading datasets...</p>
          </div>
        )}

        {/* Empty State */}
        {!loading && curatedDatasets.length === 0 && (
          <div className="bg-white rounded-lg shadow-md p-12 text-center">
            <Database className="w-16 h-16 text-gray-400 mx-auto mb-4" />
            <h3 className="text-xl font-semibold text-gray-900 mb-2">No Datasets Yet</h3>
            <p className="text-gray-600 mb-4">
              Open Claude Desktop and start curating datasets!
            </p>
            <p className="text-sm text-gray-500">
              Claude will automatically save them here via the MCP server
            </p>
          </div>
        )}

        {/* Curated Datasets List */}
        {curatedDatasets.length > 0 && (
          <div className="bg-white rounded-lg shadow-md p-6">
            <h2 className="text-xl font-bold text-gray-900 mb-4 flex items-center gap-2">
              <CheckCircle className="w-6 h-6 text-green-600" />
              Curated Datasets ({curatedDatasets.length})
            </h2>
            <div className="space-y-3">
              {curatedDatasets.map((dataset) => (
                <div
                  key={dataset.id}
                  className="border border-gray-200 rounded-lg p-4 hover:border-blue-300 transition-colors hover:shadow-md"
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-start gap-3">
                        <div className="flex-1">
                          <h3 className="font-semibold text-gray-900 text-lg">{dataset.Title}</h3>
                          <div className="flex items-center gap-3 mt-2 text-sm text-gray-600">
                            <span className="px-2 py-1 bg-blue-100 text-blue-700 rounded">
                              {dataset.Year}
                            </span>
                            <span>{dataset.Clinical_Condition}</span>
                            {dataset.Dataset_URL && (
                              <a
                                href={dataset.Dataset_URL}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="flex items-center gap-1 text-blue-600 hover:text-blue-700"
                              >
                                <ExternalLink className="w-3 h-3" />
                                View
                              </a>
                            )}
                          </div>
                          <p className="text-sm text-gray-600 mt-2 line-clamp-2">
                            {dataset.Description}
                          </p>
                          <div className="flex flex-wrap gap-2 mt-3">
                            {dataset.Physiological_Modality && dataset.Physiological_Modality !== "Not specified" && (
                              <span className="px-2 py-1 bg-purple-100 text-purple-700 rounded text-xs">
                                {dataset.Physiological_Modality.split(',')[0]}
                              </span>
                            )}
                            {dataset.Metadata_Completeness && (
                              <span className={`px-2 py-1 rounded text-xs ${
                                dataset.Metadata_Completeness === 'High' 
                                  ? 'bg-green-100 text-green-700'
                                  : dataset.Metadata_Completeness === 'Moderate'
                                  ? 'bg-yellow-100 text-yellow-700'
                                  : 'bg-red-100 text-red-700'
                              }`}>
                                {dataset.Metadata_Completeness}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                    <button
                      onClick={() => deleteDataset(dataset.id)}
                      className="ml-4 p-2 text-red-600 hover:bg-red-50 rounded transition-colors"
                      title="Remove from view"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>np
          </div>
        )}

        {/* Status Footer */}
        <div className="mt-6 text-center text-sm text-gray-500">
          <p>🤖 Powered by Claude Desktop + MCP Server</p>
          <p className="mt-1">Database: ~/Desktop/physionet-curator/web-app/public/curated_datasets.json</p>
        </div>
      </div>
    </div>
  );
}