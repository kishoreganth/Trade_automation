let ws = null;
let messages = [];
let financialMetrics = [];
let aiAnalysisResults = [];
let uniqueSymbols = new Set();
let selectedOption = 'all';

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
document.addEventListener('DOMContentLoaded', function() {
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
    refreshMessages();
});

// Place Order functionality
function setupPlaceOrder() {
    const totpInput = document.getElementById('totpInput');
    const checkTotpBtn = document.getElementById('checkTotpBtn');
    const placeOrderBtn = document.getElementById('placeOrderBtn');
    
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
    
    // Place Order button functionality
    placeOrderBtn.addEventListener('click', async function() {
        // Show confirmation dialog
        const confirmMessage = 'Are you sure you want to execute all orders from the sheet?\n\n' +
                              'This will place BUY orders (5% below LTP) and SELL orders (5% above LTP) ' +
                              'for all stocks in the market data table.';
        
        if (!confirm(confirmMessage)) {
            return;
        }
        
        // Show loading status
        showOrderStatus('loading', '⏳', 'Processing orders...');
        
        // Disable button during processing
        placeOrderBtn.disabled = true;
        placeOrderBtn.innerHTML = '<span class="btn-icon">⏳</span>Processing...';
        
        try {
            const response = await fetch('/api/execute_orders', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                }
            });
            
            const result = await response.json();
            
            if (response.ok && result.success) {
                showOrderStatus('success', '✅', result.message || 'Orders executed successfully!');
                
                // Keep button disabled after successful execution
                placeOrderBtn.innerHTML = '<span class="btn-icon">✅</span>Orders Executed';
                placeOrderBtn.style.background = '#10b981';
                
            } else {
                showOrderStatus('error', '❌', result.message || 'Failed to execute orders');
                
                // Re-enable button on error
                placeOrderBtn.disabled = false;
                placeOrderBtn.innerHTML = '<span class="btn-icon">🚀</span>PLACE ORDERS';
                placeOrderBtn.style.background = '#10b981';
            }
            
        } catch (error) {
            console.error('Error executing orders:', error);
            showOrderStatus('error', '❌', 'Error executing orders. Please try again.');
            
            // Re-enable button on error
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
        
        const tbody = document.getElementById('sheetTableBody');
        
        if (result.success && result.data.length > 0) {
            tbody.innerHTML = '';
            
            result.data.forEach(row => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${row.STOCK_NAME || ''}</td>
                    <td>${row.EXCHANGE_TOKEN || ''}</td>
                    <td>${row.GAP || ''}</td>
                    <td>${row.MARKET || ''}</td>
                    <td>${row.QUANTITY || ''}</td>
                    <td>₹${row['CLOSE PRICE'] || ''}</td>
                    <td>₹${row['BUY ORDER'] || ''}</td>
                    <td>₹${row['SELL ORDER'] || ''}</td>
                `;
                tbody.appendChild(tr);
            });
            
            console.log(`Loaded ${result.data.length} market orders from Google Sheet`);
        } else {
            tbody.innerHTML = '<tr><td colspan="8" class="loading-cell">No market data available</td></tr>';
        }
        
    } catch (error) {
        console.error('Error loading place order sheet:', error);
        document.getElementById('sheetTableBody').innerHTML = 
            '<tr><td colspan="8" class="loading-cell">Error loading market data</td></tr>';
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

