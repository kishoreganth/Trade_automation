let ws = null;
let messages = [];
let financialMetrics = [];
let aiAnalysisResults = [];
let uniqueSymbols = new Set();
let selectedOption = 'all';

// Check authentication on page load with server-side validation
async function checkAuth() {
    const sessionToken = localStorage.getItem('session_token');
    if (!sessionToken) {
        window.location.href = '/';
        return false;
    }
    
    // Validate session with server
    try {
        const response = await fetch('/api/verify_session', {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${sessionToken}`,
                'Content-Type': 'application/json'
            }
        });
        
        const data = await response.json();
        
        if (!response.ok || !data.valid) {
            // Session expired or invalid
            console.log('Session expired or invalid. Redirecting to login...');
            localStorage.removeItem('session_token');
            window.location.href = '/';
            return false;
        }
        
        // Session is valid, start periodic validation
        startSessionMonitoring();
        return true;
        
    } catch (error) {
        console.error('Session validation error:', error);
        // On network error, allow but don't start monitoring
        return true;
    }
}

// Periodic session validation (every 5 minutes)
let sessionMonitorInterval = null;

function startSessionMonitoring() {
    // Clear any existing interval
    if (sessionMonitorInterval) {
        clearInterval(sessionMonitorInterval);
    }
    
    // Check session validity every 5 minutes
    sessionMonitorInterval = setInterval(async () => {
        const sessionToken = localStorage.getItem('session_token');
        if (!sessionToken) {
            handleSessionExpired();
            return;
        }
        
        try {
            const response = await fetch('/api/verify_session', {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${sessionToken}`,
                    'Content-Type': 'application/json'
                }
            });
            
            const data = await response.json();
            
            if (!response.ok || !data.valid) {
                handleSessionExpired();
            }
        } catch (error) {
            console.error('Session monitoring error:', error);
            // Don't logout on network errors, just log
        }
    }, 5 * 60 * 1000); // 5 minutes
}

function handleSessionExpired() {
    // Clear interval
    if (sessionMonitorInterval) {
        clearInterval(sessionMonitorInterval);
        sessionMonitorInterval = null;
    }
    
    // Clear session
    localStorage.removeItem('session_token');
    
    // Show alert
    alert('Your session has expired. Please login again.');
    
    // Redirect to login
    window.location.href = '/';
}

// Add auth header to fetch requests
function getAuthHeaders() {
    const sessionToken = localStorage.getItem('session_token');
    return {
        'Authorization': `Bearer ${sessionToken}`,
        'Content-Type': 'application/json'
    };
}

// WebSocket connection
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // Connect to the same host and port as the current page
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    
    ws = new WebSocket(wsUrl);
    
    ws.onopen = function(event) {
        console.log('WebSocket connected');
        updateConnectionStatus('Connected', true);
    };
    
    ws.onmessage = function(event) {
        const data = JSON.parse(event.data);
        console.log('Received message:', data);
        
        if (data.type === 'new_message') {
            addNewMessage(data.message);
        } else if (data.type === 'messages_list') {
            loadMessages(data.messages);
        } else if (data.type === 'financial_metrics') {
            addFinancialMetrics(data.data);
        } else if (data.type === 'ai_analysis_status') {
            updateAIAnalysisStatus(data);
        } else if (data.type === 'ai_analysis_complete') {
            handleAIAnalysisComplete(data);
        } else if (data.type === 'scheduled_task') {
            handleScheduledTaskUpdate(data);
        } else if (data.type === 'job_completed') {
            handleJobCompleted(data.job);
        } else if (data.type === 'job_failed') {
            handleJobFailed(data.job);
        }
    };
    
    ws.onclose = function(event) {
        console.log('WebSocket disconnected');
        updateConnectionStatus('Disconnected', false);
        
        // Reconnect after 3 seconds
        setTimeout(connectWebSocket, 3000);
    };
    
    ws.onerror = function(error) {
        console.error('WebSocket error:', error);
        updateConnectionStatus('Error', false);
    };
}

function updateConnectionStatus(status, isConnected) {
    const statusElement = document.getElementById('connectionStatus');
    const statusDot = document.getElementById('statusDot');
    
    statusElement.textContent = status;
    statusDot.style.background = isConnected ? '#27ae60' : '#e74c3c';
}

function addNewMessage(message) {
    messages.unshift(message);
    if (message.symbol) {
        uniqueSymbols.add(message.symbol);
    }
    updateStats();
    renderMessages();
}

function loadMessages(messagesList) {
    messages = messagesList;
    uniqueSymbols.clear();
    messagesList.forEach(msg => {
        if (msg.symbol) uniqueSymbols.add(msg.symbol);
    });
    updateStats();
    renderMessages();
}

function addFinancialMetrics(data) {
    console.log('Adding financial metrics:', data);
    // Add new metrics to the beginning of the array
    data.metrics.forEach(metric => {
        financialMetrics.unshift(metric);
    });
    renderFinancialMetrics();
}

function loadFinancialMetrics(metricsList) {
    financialMetrics = metricsList;
    renderFinancialMetrics();
}

function updateStats() {
    const today = new Date().toDateString();
    const todayCount = messages.filter(msg => 
        new Date(msg.timestamp).toDateString() === today
    ).length;
    
    document.getElementById('totalMessages').textContent = messages.length;
    document.getElementById('todayMessages').textContent = todayCount;
    document.getElementById('uniqueSymbols').textContent = uniqueSymbols.size;
    
    if (messages.length > 0) {
        const lastTime = new Date(messages[0].timestamp);
        document.getElementById('lastMessageTime').textContent = 
            lastTime.toLocaleTimeString();
    }
    
    document.getElementById('lastUpdate').textContent = 
        `Last update: ${new Date().toLocaleTimeString()}`;
}

function renderMessages() {
    const tbody = document.getElementById('messagesTable');
    const symbolFilter = document.getElementById('symbolFilter').value.toLowerCase();
    const limit = parseInt(document.getElementById('limitSelect').value);
    
    let filteredMessages = messages;
    
    // Filter by symbol
    if (symbolFilter) {
        filteredMessages = filteredMessages.filter(msg => 
            msg.symbol && msg.symbol.toLowerCase().includes(symbolFilter)
        );
    }
    
    // Filter by selected option
    if (selectedOption !== 'all') {
        filteredMessages = filteredMessages.filter(msg => 
            msg.option && msg.option === selectedOption
        );
    }
    
    if (limit > 0) {
        filteredMessages = filteredMessages.slice(0, limit);
    }
    
    if (filteredMessages.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="no-messages">
                    ${symbolFilter || selectedOption !== 'all' ? 'No messages match the filter.' : 'No messages yet. Waiting for corporate announcements...'}
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = filteredMessages.map(msg => {
        const time = new Date(msg.timestamp);
        const fileLink = msg.file_url ? 
            `<a href="${msg.file_url}" target="_blank" class="file-link">📄 View File</a>` : 
            '-';
        
        const optionBadge = msg.option ? 
            `<span class="option-badge" style="background: #27ae60; color: white; padding: 2px 6px; border-radius: 3px; font-size: 0.8rem;">${msg.option.replace('_', ' ').toUpperCase()}</span>` : 
            '-';
        
        return `
            <tr class="new-message">
                <td class="timestamp">${time.toLocaleString()}</td>
                <td>${msg.symbol ? `<span class="symbol-badge">${msg.symbol}</span>` : '-'}</td>
                <td>${msg.company_name || '-'}</td>
                <td class="message-cell" title="${msg.description}">${msg.description || '-'}</td>
                <td>${optionBadge}</td>
                <td>${fileLink}</td>
                <td>${msg.chat_id}</td>
            </tr>
        `;
    }).join('');
}

function renderFinancialMetrics() {
    const tbody = document.getElementById('financialMetricsTable');
    const limit = parseInt(document.getElementById('limitSelect').value);
    
    let filteredMetrics = financialMetrics;
    
    if (limit > 0) {
        filteredMetrics = filteredMetrics.slice(0, limit);
    }
    
    if (filteredMetrics.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="10" class="no-messages">
                    No financial metrics data available yet...
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = filteredMetrics.map(metric => {
        const reportedTime = new Date(metric.reported_at);
        
        return `
            <tr class="new-message">
                <td><span class="symbol-badge">${metric.stock_symbol}</span></td>
                <td>${metric.period}</td>
                <td>${metric.year}</td>
                <td>${metric.revenue ? metric.revenue.toLocaleString() : '-'}</td>
                <td>${metric.pbt ? metric.pbt.toLocaleString() : '-'}</td>
                <td>${metric.pat ? metric.pat.toLocaleString() : '-'}</td>
                <td>${metric.total_income ? metric.total_income.toLocaleString() : '-'}</td>
                <td>${metric.other_income ? metric.other_income.toLocaleString() : '-'}</td>
                <td>${metric.eps ? metric.eps.toFixed(2) : '-'}</td>
                <td class="timestamp">${reportedTime.toLocaleString()}</td>
            </tr>
        `;
    }).join('');
}

function refreshMessages() {
    // Get the current limit setting from the UI
    const limit = parseInt(document.getElementById('limitSelect').value);
    const url = limit > 0 ? `/api/messages?limit=${limit}` : '/api/messages?limit=0';
    
    fetch(url)
        .then(response => response.json())
        .then(data => {
            loadMessages(data.messages);
        })
        .catch(error => {
            console.error('Error fetching messages:', error);
        });
}

function loadFinancialMetricsFromAPI() {
    fetch('/api/financial_metrics')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                loadFinancialMetrics(data.metrics);
            }
        })
        .catch(error => {
            console.error('Error fetching financial metrics:', error);
        });
}

function refreshData() {
    if (selectedOption === 'result_concall') {
        loadFinancialMetricsFromAPI();
    } else {
        refreshMessages();
    }
}

// Clear messages functionality removed by user request

// Option filter functionality
function handleOptionFilter(optionValue) {
    // Remove active class from all filters
    document.querySelectorAll('.option-filter').forEach(filter => {
        filter.classList.remove('active');
    });
    
    // Add active class to selected filter
    document.querySelector(`[data-option="${optionValue}"]`).classList.add('active');
    
    // Update selected option
    selectedOption = optionValue;
    
    // Show/hide appropriate table based on selection
    const messagesContainer = document.getElementById('messagesTableContainer');
    const financialContainer = document.getElementById('financialMetricsContainer');
    
    const aiAnalyzerContainer = document.getElementById('aiAnalyzerContainer');
    
    if (optionValue === 'result_concall') {
        // Show financial metrics table for board meeting outcomes
        document.querySelector('.content-area').style.display = 'flex';
        document.getElementById('placeOrderPage').style.display = 'none';
        messagesContainer.style.display = 'none';
        financialContainer.style.display = 'block';
        aiAnalyzerContainer.style.display = 'none';
        renderFinancialMetrics();
        // Load financial metrics if not already loaded
        if (financialMetrics.length === 0) {
            loadFinancialMetricsFromAPI();
        }
    } else if (optionValue === 'ai_analyzer') {
        // Show AI analyzer interface
        document.querySelector('.content-area').style.display = 'flex';
        document.getElementById('placeOrderPage').style.display = 'none';
        messagesContainer.style.display = 'none';
        financialContainer.style.display = 'none';
        aiAnalyzerContainer.style.display = 'block';
        renderAIAnalysisResults();
    } else if (optionValue === 'place_order') {
        // Show Place Order page - hide entire content area
        document.querySelector('.content-area').style.display = 'none';
        document.getElementById('placeOrderPage').style.display = 'block';
        
        // Setup open Google sheet button
        setupOpenSheetButton();
        
        // Check session status and load sheet data when page loads
        checkSessionStatus();
        loadPlaceOrderSheet();
    } else {
        // Show messages table for all other options
        document.querySelector('.content-area').style.display = 'flex';
        document.getElementById('placeOrderPage').style.display = 'none';
        messagesContainer.style.display = 'block';
        financialContainer.style.display = 'none';
        aiAnalyzerContainer.style.display = 'none';
        renderMessages();
    }
}

// AI Analyzer Functions
function renderAIAnalysisResults() {
    const tbody = document.getElementById('aiResultsTable');
    
    if (aiAnalysisResults.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="9" class="no-messages">
                    Upload a PDF file to see financial analysis results...
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = aiAnalysisResults.map(result => {
        const analyzedTime = new Date(result.analyzed_at);
        
        return `
            <tr class="new-message">
                <td>${result.period}</td>
                <td>${result.year}</td>
                <td>${result.revenue ? result.revenue.toLocaleString() : '-'}</td>
                <td>${result.pbt ? result.pbt.toLocaleString() : '-'}</td>
                <td>${result.pat ? result.pat.toLocaleString() : '-'}</td>
                <td>${result.total_income ? result.total_income.toLocaleString() : '-'}</td>
                <td>${result.other_income ? result.other_income.toLocaleString() : '-'}</td>
                <td>${result.eps ? result.eps.toFixed(2) : '-'}</td>
                <td class="timestamp">${analyzedTime.toLocaleString()}</td>
            </tr>
        `;
    }).join('');
}

function updateAIAnalysisStatus(data) {
    const uploadStatus = document.getElementById('uploadStatus');
    const statusText = document.querySelector('.status-text');
    const statusIcon = document.querySelector('.status-icon');
    const progressFill = document.getElementById('progressFill');
    
    uploadStatus.style.display = 'block';
    
    if (data.status === 'processing') {
        statusIcon.textContent = '⏳';
        statusText.textContent = data.message;
        progressFill.style.width = '50%';
    } else if (data.status === 'error') {
        statusIcon.textContent = '❌';
        statusText.textContent = data.message;
        progressFill.style.width = '0%';
        // Hide status after 5 seconds
        setTimeout(() => {
            uploadStatus.style.display = 'none';
        }, 5000);
    }
}

function handleAIAnalysisComplete(data) {
    const uploadStatus = document.getElementById('uploadStatus');
    const statusText = document.querySelector('.status-text');
    const statusIcon = document.querySelector('.status-icon');
    const progressFill = document.getElementById('progressFill');
    const aiResultsContainer = document.getElementById('aiResultsContainer');
    
    // Update status to complete
    statusIcon.textContent = '✅';
    statusText.textContent = `Analysis complete for ${data.filename}`;
    progressFill.style.width = '100%';
    
    // Process the financial metrics data
    if (data.data && data.data.quarterly_data) {
        const newResults = data.data.quarterly_data.map(quarter => ({
            period: quarter.period || '',
            year: quarter.year_ended || '',
            revenue: quarter.revenue_from_operations || 0,
            pbt: quarter.profit_before_tax || 0,
            pat: quarter.profit_after_tax || 0,
            total_income: quarter.total_income || 0,
            other_income: quarter.other_income || 0,
            eps: quarter.earnings_per_share || 0,
            analyzed_at: new Date().toISOString()
        }));
        
        // Add new results to the beginning of the array
        aiAnalysisResults.unshift(...newResults);
        
        // Show results container and render
        aiResultsContainer.style.display = 'block';
        renderAIAnalysisResults();
    }
    
    // Hide status after 3 seconds
    setTimeout(() => {
        uploadStatus.style.display = 'none';
    }, 3000);
}

async function uploadFileForAnalysis(file) {
    const formData = new FormData();
    formData.append('file', file);
    
    // Show processing status with full processing
    updateAIAnalysisStatus({
        status: 'processing',
        filename: file.name,
        message: `Processing ${file.name}... Full analysis mode: 1-2 minutes expected.`
    });
    
    // Start progress animation with timing
    const progressFill = document.getElementById('progressFill');
    const statusText = document.querySelector('.status-text');
    let progress = 0;
    let seconds = 0;
    const startTime = Date.now();
    
    const progressInterval = setInterval(() => {
        seconds++;
        progress += 1.5;  // Slower progress for more accurate timing
        if (progress <= 90) {
            progressFill.style.width = progress + '%';
        }
        // Update status text with elapsed time
        statusText.textContent = `Processing ${file.name}... ${seconds}s elapsed (full analysis mode)`;
    }, 1000); // Update every second
    
    try {
        const response = await fetch('/api/ai_analyze', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Upload failed');
        }
        
        const result = await response.json();
        console.log('Upload successful:', result);
        
        // Clear progress interval and show final timing
        clearInterval(progressInterval);
        const endTime = Date.now();
        const totalTime = ((endTime - startTime) / 1000).toFixed(1);
        
        // Show completion status with timing
        const statusIcon = document.querySelector('.status-icon');
        statusIcon.textContent = '✅';
        statusText.textContent = `Analysis completed in ${totalTime}s! 🎉`;
        progressFill.style.width = '100%';
        
        // Handle successful analysis
        handleAIAnalysisComplete({
            filename: result.filename,
            data: result.financial_metrics
        });
        
    } catch (error) {
        // Clear progress interval
        clearInterval(progressInterval);
        
        console.error('Upload error:', error);
        updateAIAnalysisStatus({
            status: 'error',
            filename: file.name,
            message: `Upload failed: ${error.message}`
        });
    }
}

function setupFileUpload() {
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');
    
    // Click to upload
    uploadArea.addEventListener('click', () => {
        fileInput.click();
    });
    
    // File input change
    fileInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file && file.type === 'application/pdf') {
            uploadFileForAnalysis(file);
        } else {
            alert('Please select a PDF file');
        }
    });
    
    // Drag and drop
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });
    
    uploadArea.addEventListener('dragleave', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
    });
    
    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            const file = files[0];
            if (file.type === 'application/pdf') {
                uploadFileForAnalysis(file);
            } else {
                alert('Please select a PDF file');
            }
        }
    });
}

// Event listeners
document.addEventListener('DOMContentLoaded', async function() {
    // Check authentication first (async now)
    const isAuthenticated = await checkAuth();
    if (!isAuthenticated) {
        return;
    }
    
    // Initialize input event listeners
    document.getElementById('symbolFilter').addEventListener('input', renderMessages);
    document.getElementById('limitSelect').addEventListener('change', function() {
        if (selectedOption === 'result_concall') {
            renderFinancialMetrics();
        } else if (selectedOption === 'ai_analyzer') {
            renderAIAnalysisResults();
        } else {
            renderMessages();
        }
    });
    
    // Add event listeners for option filters
    document.querySelectorAll('.option-filter').forEach(filter => {
        filter.addEventListener('click', () => {
            handleOptionFilter(filter.dataset.option);
        });
    });
    
    // Setup file upload functionality
    setupFileUpload();
    
    // Setup Place Order functionality
    setupPlaceOrder();
    
    // Setup refresh sheet button
    const refreshSheetBtn = document.getElementById('refreshSheetBtn');
    if (refreshSheetBtn) {
        refreshSheetBtn.addEventListener('click', loadPlaceOrderSheet);
    }
    
    // Initialize WebSocket and load messages
    connectWebSocket();
    restoreScheduledTaskStatus();
    refreshMessages();
});

// Setup Open Google Sheet Button
function setupOpenSheetButton() {
    const openSheetBtn = document.getElementById('openSheetBtn');
    if (openSheetBtn) {
        // Remove existing listeners to prevent duplicates
        openSheetBtn.replaceWith(openSheetBtn.cloneNode(true));
        const newBtn = document.getElementById('openSheetBtn');
        
        newBtn.addEventListener('click', (e) => {
            e.preventDefault();
            console.log('Opening Google Sheet in new tab...');
            window.open('https://docs.google.com/spreadsheets/d/1zftmphSqQfm0TWsUuaMl0J9mAsvQcafgmZ5U7DAXnzM/edit?gid=1933500776#gid=1933500776', '_blank', 'noopener,noreferrer');
        });
        console.log('Open Sheet button setup complete');
    } else {
        console.error('Open Sheet button not found');
    }
}

// Place Order functionality
function setupPlaceOrder() {
    const totpInput = document.getElementById('totpInput');
    const checkTotpBtn = document.getElementById('checkTotpBtn');
    const placeOrderBtn = document.getElementById('placeOrderBtn');
    const getQuotesBtn = document.getElementById('getQuotesBtn');
    
    // TOTP input validation - only allow numbers
    totpInput.addEventListener('input', function(e) {
        e.target.value = e.target.value.replace(/[^0-9]/g, '');
        if (e.target.value.length > 6) {
            e.target.value = e.target.value.slice(0, 6);
        }
    });
    
    // Auto-submit when 6 digits are entered
    totpInput.addEventListener('input', function(e) {
        if (e.target.value.length === 6) {
            setTimeout(() => {
                checkTotpBtn.click();
            }, 500);
        }
    });
    
    // Check TOTP button
    checkTotpBtn.addEventListener('click', async function() {
        const totpCode = totpInput.value.trim();
        
        if (totpCode.length !== 6) {
            showTotpStatus('error', '❌', 'Please enter a 6-digit TOTP code');
            return;
        }
        
        if (!/^\d{6}$/.test(totpCode)) {
            showTotpStatus('error', '❌', 'TOTP code must contain only numbers');
            return;
        }
        
        // Show loading status
        showTotpStatus('loading', '⏳', 'Verifying TOTP code...');
        
        try {
            const response = await fetch('/api/verify_totp', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    totp_code: totpCode
                })
            });
            
            const result = await response.json();
            
            if (response.ok && result.success) {
                showTotpStatus('success', '✅', result.message || 'TOTP verified and session established for the day');
                
                // Deactivate the check button and input
                checkTotpBtn.disabled = true;
                checkTotpBtn.innerHTML = '<span class="btn-icon">✅</span>Session Active';
                checkTotpBtn.style.background = '#10b981';
                totpInput.disabled = true;
                totpInput.style.background = '#f3f4f6';
                
                // Show session info if available
                if (result.session_info) {
                    setTimeout(() => {
                        showTotpStatus('success', '🔐', `Session established! SID: ${result.session_info.sid}`);
                    }, 2000);
                }
            } else {
                showTotpStatus('error', '❌', result.message || 'Invalid TOTP code');
            }
        } catch (error) {
            console.error('Error verifying TOTP:', error);
            showTotpStatus('error', '❌', 'Error verifying TOTP. Please try again.');
        }
    });
    
    // Get Quotes button functionality with job tracking
    getQuotesBtn.addEventListener('click', async function() {
        // Show loading status
        showQuotesStatus('loading', '⏳', 'Starting quote fetch... (3-4 minutes)');
        
        // Disable button during processing
        getQuotesBtn.disabled = true;
        getQuotesBtn.innerHTML = '<span class="btn-icon">⏳</span>Fetching...';
        
        try {
            // Start background job - returns immediately with job_id
            const response = await fetch('/api/get_quotes_updated', {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                }
            });
            
            const result = await response.json();
            
            if (response.ok && result.success && result.job_id) {
                const jobId = result.job_id;
                console.log(`GET QUOTES job started: ${jobId}`);
                
                showQuotesStatus('loading', '⏳', `Quote fetching in progress... (${result.estimated_time})`);
                
                // Poll job status every 5 seconds
                const pollInterval = setInterval(async () => {
                    try {
                        const statusResponse = await fetch(`/api/job_status/${jobId}`);
                        const statusData = await statusResponse.json();
                        
                        if (statusData.success && statusData.job) {
                            const job = statusData.job;
                            
                            if (job.status === 'completed') {
                                clearInterval(pollInterval);
                                showQuotesStatus('success', '✅', job.message || 'Quotes fetched and updated successfully!');
                                
                                // Re-enable button
                                getQuotesBtn.disabled = false;
                                getQuotesBtn.innerHTML = '<span class="btn-icon">📊</span>GET QUOTES';
                                
                                // Refresh sheet data
                                setTimeout(() => {
                                    loadPlaceOrderSheet();
                                }, 1000);
                                
                            } else if (job.status === 'failed') {
                                clearInterval(pollInterval);
                                showQuotesStatus('error', '❌', job.error || 'Failed to fetch quotes');
                                
                                // Re-enable button on error
                                getQuotesBtn.disabled = false;
                                getQuotesBtn.innerHTML = '<span class="btn-icon">📊</span>GET QUOTES';
                            } else {
                                // Update progress
                                showQuotesStatus('loading', '⏳', `${job.message} (Progress: ${job.progress}%)`);
                            }
                        }
                    } catch (pollError) {
                        console.error('Error polling job status:', pollError);
                    }
                }, 5000); // Poll every 5 seconds
                
            } else {
                showQuotesStatus('error', '❌', result.message || 'Failed to start quote fetching');
                getQuotesBtn.disabled = false;
                getQuotesBtn.innerHTML = '<span class="btn-icon">📊</span>GET QUOTES';
            }
            
        } catch (error) {
            console.error('Error starting quote fetch:', error);
            showQuotesStatus('error', '❌', 'Error starting quote fetch. Please try again.');
            getQuotesBtn.disabled = false;
            getQuotesBtn.innerHTML = '<span class="btn-icon">📊</span>GET QUOTES';
        }
    });
    
    // Place Order button functionality with job tracking
    placeOrderBtn.addEventListener('click', async function() {
        // Show confirmation dialog
        const confirmMessage = 'Are you sure you want to execute all orders from the sheet?\n\n' +
                              'This will place BUY and SELL orders for all stocks in the market data table.';
        
        if (!confirm(confirmMessage)) {
            return;
        }
        
        // Show loading status
        showOrderStatus('loading', '⏳', 'Starting order execution...');
        
        // Disable button during processing
        placeOrderBtn.disabled = true;
        placeOrderBtn.innerHTML = '<span class="btn-icon">⏳</span>Processing...';
        
        try {
            // Start background job - returns immediately with job_id
            const response = await fetch('/api/execute_orders', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                }
            });
            
            const result = await response.json();
            
            if (response.ok && result.success && result.job_id) {
                const jobId = result.job_id;
                console.log(`PLACE ORDER job started: ${jobId}`);
                
                showOrderStatus('loading', '⏳', `Executing orders in background... (${result.estimated_time})`);
                
                // Poll job status every 5 seconds
                const pollInterval = setInterval(async () => {
                    try {
                        const statusResponse = await fetch(`/api/job_status/${jobId}`);
                        const statusData = await statusResponse.json();
                        
                        if (statusData.success && statusData.job) {
                            const job = statusData.job;
                            
                            if (job.status === 'completed') {
                                clearInterval(pollInterval);
                                showOrderStatus('success', '✅', job.message || 'All orders executed successfully!');
                                
                                // Keep button disabled after successful execution
                                placeOrderBtn.innerHTML = '<span class="btn-icon">✅</span>Orders Executed';
                                placeOrderBtn.style.background = '#10b981';
                                
                            } else if (job.status === 'failed') {
                                clearInterval(pollInterval);
                                showOrderStatus('error', '❌', job.error || 'Order execution failed');
                                
                                // Re-enable button on error
                                placeOrderBtn.disabled = false;
                                placeOrderBtn.innerHTML = '<span class="btn-icon">🚀</span>PLACE ORDERS';
                                placeOrderBtn.style.background = '#10b981';
                            } else {
                                // Update progress
                                showOrderStatus('loading', '⏳', `${job.message} (Progress: ${job.progress}%)`);
                            }
                        }
                    } catch (pollError) {
                        console.error('Error polling job status:', pollError);
                    }
                }, 5000); // Poll every 5 seconds
                
            } else {
                showOrderStatus('error', '❌', result.message || 'Failed to start order execution');
                placeOrderBtn.disabled = false;
                placeOrderBtn.innerHTML = '<span class="btn-icon">🚀</span>PLACE ORDERS';
                placeOrderBtn.style.background = '#10b981';
            }
            
        } catch (error) {
            console.error('Error starting order execution:', error);
            showOrderStatus('error', '❌', 'Error starting order execution. Please try again.');
            placeOrderBtn.disabled = false;
            placeOrderBtn.innerHTML = '<span class="btn-icon">🚀</span>PLACE ORDERS';
            placeOrderBtn.style.background = '#10b981';
        }
    });
}

async function checkSessionStatus() {
    // Check if there's an active session and update UI accordingly
    try {
        const response = await fetch('/api/session_status');
        const result = await response.json();
        
        const totpInput = document.getElementById('totpInput');
        const checkTotpBtn = document.getElementById('checkTotpBtn');
        
        if (result.session_active) {
            // Session is active - show session active state
            showTotpStatus('success', '🔐', `Session active until ${new Date(result.expires_at).toLocaleString()}`);
            
            // Deactivate input and button
            totpInput.disabled = true;
            totpInput.style.background = '#f3f4f6';
            totpInput.value = '******';
            
            checkTotpBtn.disabled = true;
            checkTotpBtn.innerHTML = '<span class="btn-icon">✅</span>Session Active';
            checkTotpBtn.style.background = '#10b981';
            checkTotpBtn.style.cursor = 'not-allowed';
        } else {
            // No active session - show input form
            totpInput.disabled = false;
            totpInput.style.background = '#ffffff';
            totpInput.value = '';
            totpInput.placeholder = 'Enter 6-digit TOTP code';
            
            checkTotpBtn.disabled = false;
            checkTotpBtn.innerHTML = '<span class="btn-icon">🔐</span>Check';
            checkTotpBtn.style.background = '#3b82f6';
            checkTotpBtn.style.cursor = 'pointer';
            
            // Hide status initially
            document.getElementById('totpStatus').style.display = 'none';
        }
        
    } catch (error) {
        console.error('Error checking session status:', error);
        // Default to showing input form on error
        const totpInput = document.getElementById('totpInput');
        const checkTotpBtn = document.getElementById('checkTotpBtn');
        
        totpInput.disabled = false;
        totpInput.style.background = '#ffffff';
        checkTotpBtn.disabled = false;
        checkTotpBtn.innerHTML = '<span class="btn-icon">🔐</span>Check';
        checkTotpBtn.style.background = '#3b82f6';
    }
}

async function loadPlaceOrderSheet() {
    // Load Google Sheet data for place orders
    try {
        const response = await fetch('/api/place_order_sheet');
        const result = await response.json();
        
        const thead = document.getElementById('sheetTableHead');
        const tbody = document.getElementById('sheetTableBody');
        
        if (result.success && result.data.length > 0) {
            // Get column names from first row
            const columns = Object.keys(result.data[0]);
            
            // Create dynamic header row
            const headerRow = document.createElement('tr');
            columns.forEach(col => {
                const th = document.createElement('th');
                th.textContent = col;
                headerRow.appendChild(th);
            });
            thead.innerHTML = '';
            thead.appendChild(headerRow);
            
            // Create data rows
            tbody.innerHTML = '';
            result.data.forEach(row => {
                const tr = document.createElement('tr');
                columns.forEach(col => {
                    const td = document.createElement('td');
                    const value = row[col] || '';
                    // Add ₹ symbol for price columns
                    if (col.includes('PRICE') || col.includes('ORDER')) {
                        td.textContent = value ? `₹${value}` : '';
                    } else {
                        td.textContent = value;
                    }
                    tr.appendChild(td);
                });
                tbody.appendChild(tr);
            });
            
            console.log(`Loaded ${result.data.length} market orders with ${columns.length} columns from Google Sheet`);
        } else {
            const colSpan = thead.querySelector('th') ? thead.querySelectorAll('th').length : 1;
            thead.innerHTML = '<tr><th class="loading-cell">No Data</th></tr>';
            tbody.innerHTML = `<tr><td colspan="${colSpan}" class="loading-cell">No market data available</td></tr>`;
        }
        
    } catch (error) {
        console.error('Error loading place order sheet:', error);
        const colSpan = document.getElementById('sheetTableHead').querySelector('th') ? 
                       document.getElementById('sheetTableHead').querySelectorAll('th').length : 1;
        document.getElementById('sheetTableHead').innerHTML = '<tr><th class="loading-cell">Error</th></tr>';
        document.getElementById('sheetTableBody').innerHTML = 
            `<tr><td colspan="${colSpan}" class="loading-cell">Error loading market data</td></tr>`;
    }
}

function showTotpStatus(type, icon, message) {
    const statusDiv = document.getElementById('totpStatus');
    const statusIcon = document.getElementById('statusIcon');
    const statusMessage = document.getElementById('statusMessage');
    
    statusDiv.className = `totp-status ${type}`;
    statusIcon.textContent = icon;
    statusMessage.textContent = message;
    statusDiv.style.display = 'block';
}

function showOrderStatus(type, icon, message) {
    const statusDiv = document.getElementById('orderStatus');
    const statusIcon = document.getElementById('orderStatusIcon');
    const statusMessage = document.getElementById('orderStatusMessage');
    
    statusDiv.className = `order-status ${type}`;
    statusIcon.textContent = icon;
    statusMessage.textContent = message;
    statusDiv.style.display = 'block';
}

function showQuotesStatus(type, icon, message) {
    const statusDiv = document.getElementById('quotesStatus');
    const statusIcon = document.getElementById('quotesStatusIcon');
    const statusMessage = document.getElementById('quotesStatusMessage');
    
    statusDiv.className = `quotes-status ${type}`;
    statusIcon.textContent = icon;
    statusMessage.textContent = message;
    statusDiv.style.display = 'block';
}

// Logout function
async function logout() {
    try {
        // Clear monitoring interval
        if (sessionMonitorInterval) {
            clearInterval(sessionMonitorInterval);
            sessionMonitorInterval = null;
        }
        
        const response = await fetch('/api/logout', {
            method: 'POST',
            headers: getAuthHeaders()
        });
        
        // Clear session token regardless of response
        localStorage.removeItem('session_token');
        
        // Redirect to login
        window.location.href = '/';
        
    } catch (error) {
        console.error('Logout error:', error);
        // Still clear session and redirect on error
        localStorage.removeItem('session_token');
        window.location.href = '/';
    }
}

// ============================================================================
// SCHEDULED TASK & NOTIFICATION SYSTEM
// ============================================================================

function handleScheduledTaskUpdate(data) {
    console.log('Scheduled task update:', data);
    
    const { status, task, message, progress, timestamp } = data;
    
    // Show notification toast
    showNotificationToast(message, status);
    
    // Update scheduled task indicator (persistent)
    if (task === 'fetch_quotes') {
        updateScheduledTaskIndicator(status, message, progress);
    }
    
    // Update quotes status if on place order page and task is fetch_quotes
    if (task === 'fetch_quotes' && document.getElementById('placeOrderPage').style.display !== 'none') {
        if (status === 'started' || status === 'progress') {
            showQuotesStatus('info', '⏳', message);
        } else if (status === 'completed') {
            showQuotesStatus('success', '✅', message);
            // Auto-refresh sheet data after quotes update
            setTimeout(() => loadPlaceOrderSheet(), 2000);
        } else if (status === 'failed') {
            showQuotesStatus('error', '❌', message);
        } else if (status === 'skipped') {
            showQuotesStatus('warning', '⚠️', message);
        }
    }
}

function updateScheduledTaskIndicator(status, message, progress) {
    const indicator = document.getElementById('scheduledTaskIndicator');
    const titleEl = document.getElementById('scheduledTaskTitle');
    const messageEl = document.getElementById('scheduledTaskMessage');
    const progressContainer = document.getElementById('scheduledProgressContainer');
    const progressBar = document.getElementById('scheduledTaskProgress');
    const percentEl = document.getElementById('scheduledTaskPercent');
    const timeEl = document.getElementById('scheduledTaskTime');
    
    if (!indicator) return;
    
    const now = new Date();
    const currentTime = now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
    const currentDate = now.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
    const dateTimeStr = `${currentDate} at ${currentTime}`;
    
    if (status === 'started' || status === 'progress') {
        // Show running state with progress
        indicator.className = 'scheduled-task-status running';
        titleEl.textContent = '🔄 Auto Fetch Running';
        messageEl.textContent = message;
        progressContainer.style.display = 'flex';
        timeEl.textContent = `Started: ${dateTimeStr}`;
        
        if (progress !== undefined) {
            progressBar.style.width = `${progress}%`;
            percentEl.textContent = `${progress}%`;
        }
    } else if (status === 'completed') {
        // Show completed state (stays visible until midnight)
        indicator.className = 'scheduled-task-status completed';
        titleEl.textContent = '✅ Auto Fetch Completed';
        messageEl.textContent = message;
        progressContainer.style.display = 'none';
        timeEl.textContent = `✓ Completed: ${dateTimeStr}`;
    } else if (status === 'failed') {
        // Show failed state (stays visible)
        indicator.className = 'scheduled-task-status failed';
        titleEl.textContent = '❌ Auto Fetch Failed';
        messageEl.textContent = message;
        progressContainer.style.display = 'none';
        timeEl.textContent = `✗ Failed: ${dateTimeStr}`;
    } else if (status === 'skipped') {
        // Show skipped state (stays visible)
        indicator.className = 'scheduled-task-status skipped';
        titleEl.textContent = '⚠️ Auto Fetch Skipped';
        messageEl.textContent = message;
        progressContainer.style.display = 'none';
        timeEl.textContent = `⚠ Skipped: ${dateTimeStr}`;
    }
    
    // Save last status to localStorage with DATE for midnight reset check
    localStorage.setItem('scheduledTaskStatus', JSON.stringify({
        status, 
        message, 
        progress, 
        time: currentTime,
        date: now.toDateString()  // Used for midnight reset check
    }));
}

// Restore scheduled task status on page load
function restoreScheduledTaskStatus() {
    const saved = localStorage.getItem('scheduledTaskStatus');
    if (saved) {
        try {
            const data = JSON.parse(saved);
            const indicator = document.getElementById('scheduledTaskIndicator');
            const titleEl = document.getElementById('scheduledTaskTitle');
            const messageEl = document.getElementById('scheduledTaskMessage');
            const timeEl = document.getElementById('scheduledTaskTime');
            const progressContainer = document.getElementById('scheduledProgressContainer');
            
            if (!indicator) return;
            
            // Check if saved status is from today - if not, reset to waiting
            const today = new Date().toDateString();
            const savedDate = data.date || '';
            
            if (savedDate !== today) {
                // Previous day's status - reset to waiting for new day
                indicator.className = 'scheduled-task-status waiting';
                titleEl.textContent = '⏳ Waiting for 9:07:10 AM';
                messageEl.textContent = 'Next auto-fetch scheduled for market open';
                progressContainer.style.display = 'none';
                timeEl.textContent = '';
                localStorage.removeItem('scheduledTaskStatus');  // Clear old status
                return;
            }
            
            // Today's status - restore it
            const dateStr = new Date().toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
            
            if (data.status === 'completed') {
                indicator.className = 'scheduled-task-status completed';
                titleEl.textContent = '✅ Auto Fetch Completed Today';
                messageEl.textContent = data.message;
                progressContainer.style.display = 'none';
                timeEl.textContent = `✓ Completed: ${dateStr} at ${data.time}`;
            } else if (data.status === 'failed') {
                indicator.className = 'scheduled-task-status failed';
                titleEl.textContent = '❌ Auto Fetch Failed Today';
                messageEl.textContent = data.message;
                progressContainer.style.display = 'none';
                timeEl.textContent = `✗ Failed: ${dateStr} at ${data.time}`;
            } else if (data.status === 'skipped') {
                indicator.className = 'scheduled-task-status skipped';
                titleEl.textContent = '⚠️ Auto Fetch Skipped Today';
                messageEl.textContent = data.message;
                progressContainer.style.display = 'none';
                timeEl.textContent = `⚠ Skipped: ${dateStr} at ${data.time}`;
            }
            // If running, don't restore - will get fresh update from WebSocket
        } catch (e) {
            console.error('Error restoring scheduled task status:', e);
        }
    }
}

function handleJobCompleted(job) {
    console.log('Job completed:', job);
    showNotificationToast(job.message, 'completed');
    
    // Update specific status areas based on job type
    if (job.type === 'get_quotes') {
        showQuotesStatus('success', '✅', job.message);
        setTimeout(() => loadPlaceOrderSheet(), 2000);
    } else if (job.type === 'place_order') {
        showOrderStatus('success', '✅', job.message);
    }
}

function handleJobFailed(job) {
    console.log('Job failed:', job);
    showNotificationToast(job.message, 'failed');
    
    // Update specific status areas based on job type
    if (job.type === 'get_quotes') {
        showQuotesStatus('error', '❌', job.message);
    } else if (job.type === 'place_order') {
        showOrderStatus('error', '❌', job.message);
    }
}

function showNotificationToast(message, type = 'info') {
    // Create or get notification container
    let container = document.getElementById('notificationContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'notificationContainer';
        container.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 10000;
            display: flex;
            flex-direction: column;
            gap: 10px;
            max-width: 400px;
        `;
        document.body.appendChild(container);
    }
    
    // Create notification toast
    const toast = document.createElement('div');
    toast.className = `notification-toast ${type}`;
    
    // Set colors based on type
    let bgColor, borderColor, icon;
    switch(type) {
        case 'completed':
        case 'success':
            bgColor = 'linear-gradient(135deg, #10b981 0%, #059669 100%)';
            borderColor = '#059669';
            icon = '✅';
            break;
        case 'failed':
        case 'error':
            bgColor = 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)';
            borderColor = '#dc2626';
            icon = '❌';
            break;
        case 'warning':
        case 'skipped':
            bgColor = 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)';
            borderColor = '#d97706';
            icon = '⚠️';
            break;
        case 'started':
        case 'progress':
            bgColor = 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)';
            borderColor = '#2563eb';
            icon = '🔄';
            break;
        default:
            bgColor = 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)';
            borderColor = '#4f46e5';
            icon = 'ℹ️';
    }
    
    toast.style.cssText = `
        background: ${bgColor};
        border: 1px solid ${borderColor};
        color: white;
        padding: 12px 16px;
        border-radius: 10px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 14px;
        font-weight: 500;
        animation: slideIn 0.3s ease-out;
        cursor: pointer;
    `;
    
    toast.innerHTML = `
        <span style="font-size: 18px;">${icon}</span>
        <span style="flex: 1;">${message}</span>
        <span style="opacity: 0.7; font-size: 12px;">${new Date().toLocaleTimeString('en-IN')}</span>
    `;
    
    // Click to dismiss
    toast.onclick = () => {
        toast.style.animation = 'slideOut 0.3s ease-in';
        setTimeout(() => toast.remove(), 300);
    };
    
    container.appendChild(toast);
    
    // Auto-remove after 10 seconds (longer for important notifications)
    const duration = (type === 'completed' || type === 'failed') ? 15000 : 8000;
    setTimeout(() => {
        if (toast.parentNode) {
            toast.style.animation = 'slideOut 0.3s ease-in';
            setTimeout(() => toast.remove(), 300);
        }
    }, duration);
}

// Add CSS animation for notifications
const notificationStyles = document.createElement('style');
notificationStyles.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(notificationStyles);

