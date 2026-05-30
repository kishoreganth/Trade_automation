let ws = null;
let messages = [];
let boardMeetingResults = [];
let aiAnalysisResults = [];
let quarterlyResults = [];
let uniqueSymbols = new Set();
let selectedOption = 'all';
let selectedNavSection = 'feed'; // feed | analytics | ai_analyzer | place_order
let readMessages = new Set();
let wsConnectTimeout = null;
let pollingInterval = null;
let wsPingInterval = null;
const WS_CONNECT_TIMEOUT_MS = 5000;
const POLL_INTERVAL_MS = 30000;
const WS_PING_MS = 15000;

let msgCurrentPage = 1;
let msgTotalPages = 1;
let msgTotalFiltered = 0;
let _searchDebounce = null;
let _statsInterval = null;

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

function stopPolling() {
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

function startPolling() {
    stopPolling();
    pollingInterval = setInterval(() => {
        if (!ws || ws.readyState !== WebSocket.OPEN) refreshMessages();
    }, POLL_INTERVAL_MS);
}

// WebSocket connection with ping keepalive
function connectWebSocket() {
    if (wsConnectTimeout) {
        clearTimeout(wsConnectTimeout);
        wsConnectTimeout = null;
    }
    if (ws && ws.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host || '127.0.0.1:5000';
    const wsUrl = `${protocol}//${host}/ws`;

    try {
        ws = new WebSocket(wsUrl);
    } catch (e) {
        console.error('WebSocket create error:', e);
        startPolling();
        setTimeout(connectWebSocket, 10000);
        return;
    }

    wsConnectTimeout = setTimeout(() => {
        if (ws && ws.readyState !== WebSocket.OPEN) {
            console.warn('WebSocket connection timeout – using polling');
            ws.close();
            ws = null;
            startPolling();
            setTimeout(connectWebSocket, 10000);
        }
        wsConnectTimeout = null;
    }, WS_CONNECT_TIMEOUT_MS);

    ws.onopen = function(event) {
        if (wsConnectTimeout) {
            clearTimeout(wsConnectTimeout);
            wsConnectTimeout = null;
        }
        stopPolling();
        startWsPing();
        console.log('WebSocket connected');
        updateConnectionStatus('Connected', true);
        refreshMessages();
    };

    ws.onmessage = function(event) {
        if (event.data === 'pong') return;
        const data = JSON.parse(event.data);
        if (data.type === 'connected') {
            // initial fetch already handled by DOMContentLoaded
        } else if (data.type === 'new_message') {
            addNewMessage(data.message);
        } else if (data.type === 'quarterly_results') {
            loadQuarterlyResults();
            loadBoardMeetingResults();
        } else if (data.type === 'ai_analysis_status') {
            updateAIAnalysisStatus(data);
        } else if (data.type === 'ai_analysis_complete') {
            handleAIAnalysisComplete(data);
        } else if (data.type === 'scheduled_task') {
            handleScheduledTaskUpdate(data);
        } else if (data.type === 'extraction_status_update') {
            handleExtractionStatusUpdate(data);
        } else if (data.type === 'job_completed') {
            handleJobCompleted(data.job);
        } else if (data.type === 'job_failed') {
            handleJobFailed(data.job);
        }
    };

    ws.onclose = function(event) {
        ws = null;
        stopWsPing();
        if (wsConnectTimeout) {
            clearTimeout(wsConnectTimeout);
            wsConnectTimeout = null;
        }
        updateConnectionStatus('Reconnecting...', false);
        startPolling();
        setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = function(error) {
        console.error('WebSocket error:', error);
    };
}

function startWsPing() {
    stopWsPing();
    wsPingInterval = setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send('ping');
        }
    }, WS_PING_MS);
}

function stopWsPing() {
    if (wsPingInterval) {
        clearInterval(wsPingInterval);
        wsPingInterval = null;
    }
}

function updateConnectionStatus(status, isConnected) {
    const statusElement = document.getElementById('connectionStatus');
    const statusDot = document.getElementById('statusDot');
    
    statusElement.textContent = status;
    const color = isConnected ? 'var(--green)' : status.includes('Reconnecting') ? '#f59e0b' : 'var(--red)';
    statusDot.style.background = color;
}

function addNewMessage(message) {
    if (msgCurrentPage === 1) {
        const perPage = parseInt(document.getElementById('limitSelect').value) || 50;
        messages.unshift(message);
        if (messages.length > perPage) messages.pop();
        renderMessageRows(messages);
    }
    fetchStats();
    updateUnreadBadges();
}

function loadMessages(messagesList) {
    messages = messagesList;
    renderMessageRows(messages);
    updateUnreadBadges();
}

function updateSectorFilterOptions() {
    const sectorFilter = document.getElementById('sectorFilter');
    if (!sectorFilter) return;
    const currentValue = sectorFilter.value;
    fetch('/api/sectors')
        .then(r => r.json())
        .then(data => {
            if (!data.success) return;
            sectorFilter.innerHTML = '<option value="">All Sectors</option>';
            data.sectors.forEach(sector => {
                const opt = document.createElement('option');
                opt.value = sector;
                opt.textContent = sector;
                sectorFilter.appendChild(opt);
            });
            if (data.sectors.includes(currentValue)) sectorFilter.value = currentValue;
        })
        .catch(() => {});
}

function loadBoardMeetingResults() {
    fetch('/api/quarterly_results')
        .then(response => response.json())
        .then(data => {
            if (data.success && data.results) {
                boardMeetingResults = data.results;
                renderBoardMeetingResults();
            }
        })
        .catch(error => {
            console.error('Error fetching board meeting results:', error);
        });
}

function animateCount(el, target) {
    const current = parseInt(el.dataset.count || '0');
    if (current === target) return;
    el.dataset.count = target;
    const duration = 400;
    const start = performance.now();
    function step(now) {
        const progress = Math.min((now - start) / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.round(current + (target - current) * eased).toLocaleString();
        if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
}

function updateStats() { fetchStats(); }

function fetchStats() {
    fetch('/api/stats')
        .then(r => r.json())
        .then(data => {
            if (!data.success) return;
            animateCount(document.getElementById('totalMessages'), data.total_messages);
            animateCount(document.getElementById('todayMessages'), data.today_messages);
            animateCount(document.getElementById('uniqueSymbols'), data.unique_symbols);
            if (data.last_message_time) {
                document.getElementById('lastMessageTime').textContent =
                    new Date(data.last_message_time).toLocaleTimeString();
            }
            document.getElementById('lastUpdate').textContent =
                `Last update: ${new Date().toLocaleTimeString()}`;
        })
        .catch(() => {});
}

function renderMessages() {
    fetchMessages(msgCurrentPage);
}

function fetchMessages(page) {
    const search = (document.getElementById('globalSearch') || document.getElementById('symbolFilter')).value.trim();
    const perPage = parseInt(document.getElementById('limitSelect').value) || 50;
    const exchangeFilter = document.getElementById('exchangeFilter');
    const sectorFilter = document.getElementById('sectorFilter');
    const exchange = exchangeFilter ? exchangeFilter.value : '';
    const sector = sectorFilter ? sectorFilter.value : '';
    const option = (selectedOption && selectedOption !== 'all' && selectedOption !== 'pe_pending' && selectedOption !== 'pe_reviewed' && selectedOption !== 'stock_value' && selectedOption !== 'ai_analyzer' && selectedOption !== 'place_order' && selectedOption !== 'result_concall') ? selectedOption : '';

    const params = new URLSearchParams({ page, per_page: perPage });
    if (search) params.set('search', search);
    if (option) params.set('option', option);
    if (exchange) params.set('exchange', exchange);
    if (sector) params.set('sector', sector);

    fetch(`/api/messages?${params}`)
        .then(r => r.json())
        .then(data => {
            if (!data.success) return;
            messages = data.messages;
            msgCurrentPage = data.page;
            msgTotalPages = data.total_pages;
            msgTotalFiltered = data.total_filtered;
            renderMessageRows(messages);
            renderPaginationControls();
        })
        .catch(err => console.error('Error fetching messages:', err));
}

function _esc(str) {
    if (!str) return '';
    return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function renderMessageRows(messagesList) {
    const tbody = document.getElementById('messagesTable');
    const colspan = 7;

    if (!messagesList || messagesList.length === 0) {
        tbody.innerHTML = `<tr><td colspan="${colspan}" class="no-messages">No messages match the filter.</td></tr>`;
        return;
    }

    tbody.innerHTML = messagesList.map(msg => {
        const time = new Date(msg.timestamp);
        const fileLink = msg.file_url ?
            `<a href="${msg.file_url}" target="_blank" class="file-link">View File</a>` : '-';
        const exchange = (msg.exchange || 'NSE').trim();
        const exchangeBadge = exchange === 'BSE' ?
            '<span class="exchange-badge bse">BSE</span>' :
            '<span class="exchange-badge nse">NSE</span>';
        const descText = _esc(msg.description || '-');
        return `
            <tr class="new-message">
                <td class="timestamp">${time.toLocaleString()}</td>
                <td>${exchangeBadge}</td>
                <td>${msg.symbol ? `<span class="symbol-badge">${_esc(msg.symbol)}</span>` : '-'}</td>
                <td>${_esc(msg.company_name) || '-'}</td>
                <td>${_esc((msg.sector || '-').trim())}</td>
                <td class="message-cell" title="${descText}">${descText}</td>
                <td>${fileLink}</td>
            </tr>`;
    }).join('');
}

function renderPaginationControls() {
    const wrap = document.getElementById('msgPagination');
    if (!wrap) return;

    wrap.style.display = msgTotalPages > 0 ? 'flex' : 'none';
    document.getElementById('msgFirstBtn').disabled = msgCurrentPage <= 1;
    document.getElementById('msgPrevBtn').disabled = msgCurrentPage <= 1;
    document.getElementById('msgNextBtn').disabled = msgCurrentPage >= msgTotalPages;
    document.getElementById('msgLastBtn').disabled = msgCurrentPage >= msgTotalPages;
    document.getElementById('msgTotalFiltered').textContent = `${msgTotalFiltered.toLocaleString()} messages`;
    document.getElementById('msgPageInput').max = msgTotalPages;
    document.getElementById('msgPageInput').placeholder = `${msgCurrentPage}/${msgTotalPages}`;

    const container = document.getElementById('msgPageNumbers');
    const pages = _buildPageList(msgCurrentPage, msgTotalPages, 7);
    container.innerHTML = pages.map(p => {
        if (p === '...') return `<span class="msg-page-ellipsis">...</span>`;
        const cls = p === msgCurrentPage ? 'msg-page-num active' : 'msg-page-num';
        return `<button class="${cls}" data-page="${p}">${p}</button>`;
    }).join('');
}

function _buildPageList(current, total, maxVisible) {
    if (total <= maxVisible) return Array.from({length: total}, (_, i) => i + 1);
    const pages = [];
    const half = Math.floor((maxVisible - 4) / 2);
    let start = Math.max(2, current - half);
    let end = Math.min(total - 1, current + half);
    if (current - half < 2) end = Math.min(total - 1, maxVisible - 2);
    if (current + half > total - 1) start = Math.max(2, total - maxVisible + 3);
    pages.push(1);
    if (start > 2) pages.push('...');
    for (let i = start; i <= end; i++) pages.push(i);
    if (end < total - 1) pages.push('...');
    pages.push(total);
    return pages;
}

function renderBoardMeetingResults() {
    const tbody = document.getElementById('financialMetricsTable');
    const limit = parseInt(document.getElementById('limitSelect').value);

    let filtered = boardMeetingResults;
    if (limit > 0) {
        filtered = filtered.slice(0, limit);
    }

    if (filtered.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="10" class="no-messages">
                    No board meeting results data available yet...
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = filtered.map(r => {
        const sd = r.standalone_data || {};
        const cd = r.consolidated_data || {};
        const data = sd.revenue ? sd : cd;
        const updatedTime = new Date(r.updated_at);
        const extSt = r.extraction_status || 'completed';
        const isFailed = extSt === 'failed';
        const isQueued = extSt === 'queued';
        const isProc = extSt === 'processing';
        const isPend = isFailed || isQueued || isProc;
        let statusBadge = '';
        if (isFailed) statusBadge = ' <span class="pe-ext-badge pe-ext-failed">FAILED</span>';
        else if (isQueued) statusBadge = ' <span class="pe-ext-badge pe-ext-queued">QUEUED</span>';
        else if (isProc) statusBadge = ' <span class="pe-ext-badge pe-ext-processing"><span class="pe-ext-spinner"></span></span>';
        else statusBadge = ' <span class="pe-ext-badge pe-ext-success">SUCCESS</span>';
        const retryCell = isFailed
            ? `<button class="pe-retry-btn" onclick="peRetryExtraction('${r.stock_symbol}', this)">${_SVG_REFRESH} Retry</button>`
            : '';

        return `
            <tr class="new-message ${isPend ? 'pe-row-pending' : ''}">
                <td><span class="symbol-badge">${r.stock_symbol}</span>${statusBadge}</td>
                <td>${isPend ? '-' : (r.quarter || '-')}</td>
                <td>${isPend ? '-' : (r.financial_year || '-')}</td>
                <td>${isPend ? '-' : (data.revenue ? Number(data.revenue).toLocaleString() : '-')}</td>
                <td>${isPend ? '-' : (data.profit_before_tax ? Number(data.profit_before_tax).toLocaleString() : '-')}</td>
                <td>${isPend ? '-' : (data.profit_after_tax ? Number(data.profit_after_tax).toLocaleString() : '-')}</td>
                <td>${isPend ? '-' : (data.total_income ? Number(data.total_income).toLocaleString() : '-')}</td>
                <td>${isPend ? '-' : (data.other_income ? Number(data.other_income).toLocaleString() : '-')}</td>
                <td>${isPend ? retryCell : (r.eps_basic_standalone ? Number(r.eps_basic_standalone).toFixed(2) : (r.eps_basic_consolidated ? Number(r.eps_basic_consolidated).toFixed(2) : '-'))}</td>
                <td class="timestamp">${updatedTime.toLocaleString()}</td>
            </tr>
        `;
    }).join('');
}

function refreshMessages() {
    fetchMessages(msgCurrentPage);
    fetchStats();
}

function loadFinancialMetricsFromAPI() {
    loadBoardMeetingResults();
}

function refreshData() {
    if (selectedOption === 'result_concall') {
        loadFinancialMetricsFromAPI();
    } else if (selectedOption === 'pe_pending' || selectedOption === 'pe_reviewed' || selectedOption === 'stock_value' || selectedOption === 'ai_analyzer' || selectedOption === 'place_order') {
        // analytics/standalone views don't need message refresh
    } else {
        refreshMessages();
    }
}

// Clear messages functionality removed by user request

function optionMatches(msgOption, filterOption) {
    if (msgOption === filterOption) return true;
    if (filterOption === 'quarterly_result' && msgOption === 'quaterly_result') return true;
    return false;
}

// Calculate unread count for a specific option
function getUnreadCount(option) {
    if (option === 'all') {
        return messages.filter(msg => {
            const msgId = msg.id || `${msg.timestamp}_${msg.symbol}_${msg.chat_id}`;
            return !readMessages.has(msgId);
        }).length;
    }
    return messages.filter(msg => {
        const msgId = msg.id || `${msg.timestamp}_${msg.symbol}_${msg.chat_id}`;
        return optionMatches(msg.option, option) && !readMessages.has(msgId);
    }).length;
}

function updateUnreadBadges() {
    const messageOptions = ['all', 'quarterly_result', 'investor_presentation', 'concall', 
                           'monthly_business_update', 'fund_raising', 'result_concall'];
    
    let totalUnread = 0;
    messageOptions.forEach(option => {
        const filterButton = document.querySelector(`.flyout-option[data-option="${option}"]`);
        if (!filterButton) return;
        
        const existingBadge = filterButton.querySelector('.unread-badge');
        if (existingBadge) existingBadge.remove();
        
        const unreadCount = getUnreadCount(option);
        if (option !== 'all') totalUnread += unreadCount;
        
        if (unreadCount > 0) {
            const badge = document.createElement('span');
            badge.className = 'unread-badge';
            badge.textContent = unreadCount > 99 ? '99+' : unreadCount.toString();
            filterButton.appendChild(badge);
        }
    });

    // Update rail badge for Feed
    const feedRail = document.querySelector('.rail-item[data-nav="feed"]');
    if (feedRail) {
        const existing = feedRail.querySelector('.rail-badge');
        if (existing) existing.remove();
        if (totalUnread > 0) {
            const badge = document.createElement('span');
            badge.className = 'rail-badge';
            badge.textContent = totalUnread > 99 ? '99+' : totalUnread.toString();
            feedRail.appendChild(badge);
        }
    }
}

// Mark messages as read when viewing a filter
function markMessagesAsRead(option) {
    if (option === 'all') {
        messages.forEach(msg => {
            const msgId = msg.id || `${msg.timestamp}_${msg.symbol}_${msg.chat_id}`;
            readMessages.add(msgId);
        });
    } else {
        messages.forEach(msg => {
            if (optionMatches(msg.option, option)) {
                const msgId = msg.id || `${msg.timestamp}_${msg.symbol}_${msg.chat_id}`;
                readMessages.add(msgId);
            }
        });
    }
    updateUnreadBadges();
}

// ============================================
// Navigation: Rail + Flyout
// ============================================
function showContentForOption(optionValue) {
    const messagesContainer = document.getElementById('messagesTableContainer');
    const financialContainer = document.getElementById('financialMetricsContainer');
    const analyticsContainer = document.getElementById('analyticsContainer');
    const aiAnalyzerContainer = document.getElementById('aiAnalyzerContainer');
    const placeOrderPage = document.getElementById('placeOrderPage');
    const contentArea = document.querySelector('.content-area');
    const globalControls = document.querySelector('.controls');
    const globalStats = document.querySelector('.stats');

    contentArea.style.display = 'flex';
    placeOrderPage.style.display = 'none';
    messagesContainer.style.display = 'none';
    financialContainer.style.display = 'none';
    analyticsContainer.style.display = 'none';
    aiAnalyzerContainer.style.display = 'none';

    const isAnalytics = (optionValue === 'pe_pending' || optionValue === 'pe_reviewed' || optionValue === 'stock_value');
    if (globalControls) globalControls.style.display = isAnalytics ? 'none' : '';
    if (globalStats) globalStats.style.display = isAnalytics ? 'none' : '';

    if (isAnalytics) {
        analyticsContainer.style.display = 'block';
        const isPE = (optionValue === 'pe_pending' || optionValue === 'pe_reviewed');
        document.getElementById('peAnalysisView').style.display = isPE ? 'block' : 'none';
        document.getElementById('stockValueView').style.display = optionValue === 'stock_value' ? 'block' : 'none';
        if (isPE) {
            const newView = optionValue === 'pe_pending' ? 'pending' : 'reviewed';
            const viewChanged = peActiveView !== newView;
            if (viewChanged && _peAbortCtrl) _peAbortCtrl.abort();
            peActiveView = newView;
            _updatePEViewHeader();
            if (viewChanged) {
                peCurrentPage = 1;
                peAnalysisData = [];
                _peServerFilterOptions = null;
                renderPEAnalysis();
            }
            if (!_peFiltersInitialized) {
                _peInitDefaultFilters();
            }
            loadPEFilterOptions();
            loadPEAnalysis();
        } else if (optionValue === 'stock_value') {
            loadAnalyticsReport();
        }
    } else if (optionValue === 'result_concall') {
        financialContainer.style.display = 'block';
        renderBoardMeetingResults();
        if (boardMeetingResults.length === 0) loadBoardMeetingResults();
    } else if (optionValue === 'ai_analyzer') {
        aiAnalyzerContainer.style.display = 'block';
        renderAIAnalysisResults();
    } else if (optionValue === 'place_order') {
        contentArea.style.display = 'none';
        placeOrderPage.style.display = 'block';
        setupOpenSheetButton();
        checkSessionStatus();
        loadPlaceOrderSheet();
        loadLastActions();
    } else {
        messagesContainer.style.display = 'block';
        msgCurrentPage = 1;
        fetchMessages(1);
    }
}

function handleOptionFilter(optionValue) {
    document.querySelectorAll('.flyout-option').forEach(el => el.classList.remove('active'));
    const target = document.querySelector(`.flyout-option[data-option="${optionValue}"]`);
    if (target) target.classList.add('active');

    markMessagesAsRead(optionValue);
    selectedOption = optionValue;
    showContentForOption(optionValue);
    updateUnreadBadges();
}

function openFlyoutOnHover(navValue) {
    document.querySelectorAll('.rail-item').forEach(el => el.classList.remove('active'));
    const target = document.querySelector(`.rail-item[data-nav="${navValue}"]`);
    if (target) target.classList.add('active');
    selectedNavSection = navValue;

    const panel = document.getElementById('flyoutPanel');
    const header = document.getElementById('flyoutHeader');
    const feedSection = document.getElementById('flyoutFeed');
    const analyticsSection = document.getElementById('flyoutAnalytics');

    if (navValue === 'feed') {
        header.textContent = 'FEED';
        feedSection.style.display = 'flex';
        analyticsSection.style.display = 'none';
        document.querySelectorAll('.flyout-option').forEach(el => el.classList.remove('active'));
        const opt = document.querySelector(`#flyoutFeed .flyout-option[data-option="${selectedOption}"]`);
        if (opt) opt.classList.add('active');
    } else if (navValue === 'analytics') {
        header.textContent = 'ANALYTICS';
        feedSection.style.display = 'none';
        analyticsSection.style.display = 'flex';
        document.querySelectorAll('.flyout-option').forEach(el => el.classList.remove('active'));
        const analyticsOpt = (selectedOption === 'pe_pending' || selectedOption === 'pe_reviewed' || selectedOption === 'stock_value') ? selectedOption : 'pe_pending';
        const opt = document.querySelector(`#flyoutAnalytics .flyout-option[data-option="${analyticsOpt}"]`);
        if (opt) opt.classList.add('active');
    }
    panel.classList.add('open');
    const backdrop = document.getElementById('flyoutBackdrop');
    if (backdrop) backdrop.classList.add('visible');
}

function openFlyout(section) {
    const panel = document.getElementById('flyoutPanel');
    const backdrop = document.getElementById('flyoutBackdrop');
    const header = document.getElementById('flyoutHeader');
    const feedSection = document.getElementById('flyoutFeed');
    const analyticsSection = document.getElementById('flyoutAnalytics');

    if (section === 'feed') {
        header.textContent = 'FEED';
        feedSection.style.display = 'flex';
        analyticsSection.style.display = 'none';
    } else if (section === 'analytics') {
        header.textContent = 'ANALYTICS';
        feedSection.style.display = 'none';
        analyticsSection.style.display = 'flex';
    }
    panel.classList.add('open');
    if (backdrop) backdrop.classList.add('visible');
}

function closeFlyout() {
    document.getElementById('flyoutPanel').classList.remove('open');
    const backdrop = document.getElementById('flyoutBackdrop');
    if (backdrop) backdrop.classList.remove('visible');
}

function handleRailClick(navValue) {
    document.querySelectorAll('.rail-item').forEach(el => el.classList.remove('active'));
    const target = document.querySelector(`.rail-item[data-nav="${navValue}"]`);
    if (target) target.classList.add('active');

    selectedNavSection = navValue;

    if (navValue === 'feed') {
        openFlyout('feed');
        if (selectedOption === 'pe_pending' || selectedOption === 'pe_reviewed' || selectedOption === 'stock_value') {
            selectedOption = 'all';
        }
        document.querySelectorAll('.flyout-option').forEach(el => el.classList.remove('active'));
        const opt = document.querySelector(`#flyoutFeed .flyout-option[data-option="${selectedOption}"]`);
        if (opt) opt.classList.add('active');
        showContentForOption(selectedOption);
    } else if (navValue === 'analytics') {
        openFlyout('analytics');
        if (selectedOption !== 'pe_pending' && selectedOption !== 'pe_reviewed' && selectedOption !== 'stock_value') {
            selectedOption = 'pe_pending';
        }
        document.querySelectorAll('.flyout-option').forEach(el => el.classList.remove('active'));
        const opt = document.querySelector(`#flyoutAnalytics .flyout-option[data-option="${selectedOption}"]`);
        if (opt) opt.classList.add('active');
        showContentForOption(selectedOption);
    } else if (navValue === 'ai_analyzer') {
        closeFlyout();
        selectedOption = 'ai_analyzer';
        showContentForOption('ai_analyzer');
    } else if (navValue === 'place_order') {
        closeFlyout();
        selectedOption = 'place_order';
        showContentForOption('place_order');
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
    const statusText = uploadStatus.querySelector('.status-text');
    const statusIcon = uploadStatus.querySelector('.status-icon');
    const progressFill = document.getElementById('progressFill');
    
    uploadStatus.style.display = 'block';
    
    if (data.status === 'processing') {
        statusIcon.innerHTML = iconHtml('loader-2', 'spin');
        statusText.textContent = data.message;
        progressFill.style.width = '50%';
    } else if (data.status === 'error') {
        statusIcon.innerHTML = iconHtml('x-circle');
        statusText.textContent = data.message;
        progressFill.style.width = '0%';
        setTimeout(() => {
            uploadStatus.style.display = 'none';
        }, 5000);
    }
}

function handleAIAnalysisComplete(data) {
    const uploadStatus = document.getElementById('uploadStatus');
    const statusText = uploadStatus.querySelector('.status-text');
    const statusIcon = uploadStatus.querySelector('.status-icon');
    const progressFill = document.getElementById('progressFill');
    const aiResultsContainer = document.getElementById('aiResultsContainer');
    
    statusIcon.innerHTML = iconHtml('check-circle');
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
    
    const uploadStatus = document.getElementById('uploadStatus');
    const progressFill = document.getElementById('progressFill');
    const statusText = uploadStatus.querySelector('.status-text');
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
        
        const statusIcon = uploadStatus.querySelector('.status-icon');
        statusIcon.innerHTML = iconHtml('check-circle');
        statusText.textContent = `Analysis completed in ${totalTime}s!`;
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
    
    // Initialize input event listeners with debounced search
    const searchEl = document.getElementById('globalSearch') || document.getElementById('symbolFilter');
    searchEl.addEventListener('input', function() {
        clearTimeout(_searchDebounce);
        _searchDebounce = setTimeout(() => { msgCurrentPage = 1; fetchMessages(1); }, 300);
    });
    const exchangeFilterEl = document.getElementById('exchangeFilter');
    if (exchangeFilterEl) exchangeFilterEl.addEventListener('change', () => { msgCurrentPage = 1; fetchMessages(1); });
    const sectorFilterEl = document.getElementById('sectorFilter');
    if (sectorFilterEl) sectorFilterEl.addEventListener('change', () => { msgCurrentPage = 1; fetchMessages(1); });
    document.getElementById('limitSelect').addEventListener('change', function() {
        if (selectedOption === 'result_concall') {
            renderBoardMeetingResults();
        } else if (selectedOption === 'ai_analyzer') {
            renderAIAnalysisResults();
        } else if (selectedOption !== 'pe_pending' && selectedOption !== 'pe_reviewed' && selectedOption !== 'stock_value') {
            msgCurrentPage = 1;
            fetchMessages(1);
        }
    });

    // Pagination buttons
    document.getElementById('msgFirstBtn').addEventListener('click', () => fetchMessages(1));
    document.getElementById('msgPrevBtn').addEventListener('click', () => {
        if (msgCurrentPage > 1) fetchMessages(msgCurrentPage - 1);
    });
    document.getElementById('msgNextBtn').addEventListener('click', () => {
        if (msgCurrentPage < msgTotalPages) fetchMessages(msgCurrentPage + 1);
    });
    document.getElementById('msgLastBtn').addEventListener('click', () => fetchMessages(msgTotalPages));
    document.getElementById('msgPageNumbers').addEventListener('click', (e) => {
        const btn = e.target.closest('[data-page]');
        if (btn) fetchMessages(parseInt(btn.dataset.page));
    });
    document.getElementById('msgGoBtn').addEventListener('click', () => {
        const val = parseInt(document.getElementById('msgPageInput').value);
        if (val >= 1 && val <= msgTotalPages) fetchMessages(val);
        document.getElementById('msgPageInput').value = '';
    });
    document.getElementById('msgPageInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') document.getElementById('msgGoBtn').click();
    });

    // Load sectors from server, stats from server
    updateSectorFilterOptions();
    fetchStats();
    _statsInterval = setInterval(fetchStats, 30000);

    // Initial messages fetch
    fetchMessages(1);
    
    // Rail click handlers
    document.querySelectorAll('.rail-item[data-nav]').forEach(el => {
        el.addEventListener('click', () => handleRailClick(el.dataset.nav));
    });

    // Hover to open flyout for Feed and Analytics
    let flyoutHoverTimeout = null;
    const rail = document.querySelector('.sidebar-rail');
    const flyout = document.getElementById('flyoutPanel');

    function scheduleCloseFlyout() {
        if (flyoutHoverTimeout) clearTimeout(flyoutHoverTimeout);
        flyoutHoverTimeout = setTimeout(() => {
            if (selectedNavSection === 'feed' || selectedNavSection === 'analytics') {
                closeFlyout();
            }
            flyoutHoverTimeout = null;
        }, 0);
    }

    function cancelCloseFlyout() {
        if (flyoutHoverTimeout) {
            clearTimeout(flyoutHoverTimeout);
            flyoutHoverTimeout = null;
        }
    }

    rail.querySelectorAll('.rail-item[data-nav="feed"], .rail-item[data-nav="analytics"]').forEach(el => {
        el.addEventListener('mouseenter', () => {
            cancelCloseFlyout();
            openFlyoutOnHover(el.dataset.nav);
        });
    });
    rail.addEventListener('mouseleave', () => scheduleCloseFlyout());
    flyout.addEventListener('mouseenter', () => cancelCloseFlyout());
    flyout.addEventListener('mouseleave', () => scheduleCloseFlyout());

    // Flyout option click handlers
    document.getElementById('flyoutPanel').addEventListener('click', (e) => {
        const opt = e.target.closest('.flyout-option');
        if (opt && opt.dataset.option) {
            handleOptionFilter(opt.dataset.option);
        }
    });

    // Close flyout when clicking the backdrop
    document.getElementById('flyoutBackdrop').addEventListener('click', () => closeFlyout());

    // Open Feed flyout by default
    openFlyout('feed');
    
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
    
    // Initialize unread badges after messages are loaded
    setTimeout(() => {
        updateUnreadBadges();
    }, 1000);
    
    // Always load config first (even if Place Order page not visible)
    // This ensures scheduledTimeDisplay is updated everywhere
    loadScheduledFetchConfig().then((config) => {
        // Restore status after config is loaded
        restoreScheduledTaskStatus();
        
        // If Place Order page is visible, also update the indicator
        if (document.getElementById('placeOrderPage') && 
            document.getElementById('placeOrderPage').style.display !== 'none') {
            // Indicator will be updated by restoreScheduledTaskStatus
        }
    });
    
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

// ============================================
// LAST ACTIONS TRACKING (persistent timestamps)
// ============================================

// Load and display last action timestamps
async function loadLastActions() {
    try {
        const response = await fetch('/api/last_actions');
        const data = await response.json();
        
        if (data.success) {
            // Update quotes hint
            const lastQuotesEl = document.getElementById('lastQuotesTime');
            const lastQuotesHint = document.getElementById('lastQuotesHint');
            if (lastQuotesEl && data.last_quotes) {
                lastQuotesEl.textContent = formatLastActionTime(data.last_quotes);
                // Add 'recent' class if within last hour
                if (isRecent(data.last_quotes)) {
                    lastQuotesHint.classList.add('recent');
                } else {
                    lastQuotesHint.classList.remove('recent');
                }
            }
            
            // Update order hint
            const lastOrderEl = document.getElementById('lastOrderTime');
            const lastOrderHint = document.getElementById('lastOrderHint');
            if (lastOrderEl && data.last_order) {
                lastOrderEl.textContent = formatLastActionTime(data.last_order);
                // Add 'recent' class if within last hour
                if (isRecent(data.last_order)) {
                    lastOrderHint.classList.add('recent');
                } else {
                    lastOrderHint.classList.remove('recent');
                }
            }
        }
    } catch (error) {
        console.error('Error loading last actions:', error);
    }
}

// Update last action timestamp on server
async function updateLastAction(actionType) {
    try {
        const response = await fetch(`/api/last_actions/${actionType}`, {
            method: 'POST'
        });
        const data = await response.json();
        
        if (data.success) {
            // Refresh the display
            loadLastActions();
        }
    } catch (error) {
        console.error(`Error updating last ${actionType} action:`, error);
    }
}

// Format timestamp for display (e.g., "Today 09:15 AM" or "05 Jan 09:15 AM")
function formatLastActionTime(isoString) {
    if (!isoString) return '--';
    
    try {
        const date = new Date(isoString);
        const now = new Date();
        
        const timeStr = date.toLocaleTimeString('en-IN', { 
            hour: '2-digit', 
            minute: '2-digit',
            hour12: true 
        });
        
        // Check if today
        const isToday = date.toDateString() === now.toDateString();
        
        // Check if yesterday
        const yesterday = new Date(now);
        yesterday.setDate(yesterday.getDate() - 1);
        const isYesterday = date.toDateString() === yesterday.toDateString();
        
        if (isToday) {
            return `Today ${timeStr}`;
        } else if (isYesterday) {
            return `Yesterday ${timeStr}`;
        } else {
            const dateStr = date.toLocaleDateString('en-IN', { 
                day: '2-digit', 
                month: 'short' 
            });
            return `${dateStr} ${timeStr}`;
        }
    } catch (e) {
        return '--';
    }
}

// Check if timestamp is within last hour (for highlighting)
function isRecent(isoString) {
    if (!isoString) return false;
    try {
        const date = new Date(isoString);
        const now = new Date();
        const hourAgo = new Date(now.getTime() - 60 * 60 * 1000);
        return date > hourAgo;
    } catch (e) {
        return false;
    }
}

// ============================================

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
                checkTotpBtn.innerHTML = `${_SVG_CHECK_CIRCLE} Session Active`;
                checkTotpBtn.style.background = 'var(--green)';
                totpInput.disabled = true;
                totpInput.style.background = '';
                
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
        getQuotesBtn.innerHTML = `${_SVG_LOADER_SPIN} Fetching...`;
        
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
                                
                                // Update last quotes timestamp
                                updateLastAction('quotes');
                                
                                // Re-enable button
                                getQuotesBtn.disabled = false;
                                getQuotesBtn.innerHTML = `${_SVG_CANDLESTICK} GET QUOTES`;
                                
                                // Refresh sheet data
                                setTimeout(() => {
                                    loadPlaceOrderSheet();
                                }, 1000);
                                
                            } else if (job.status === 'failed') {
                                clearInterval(pollInterval);
                                showQuotesStatus('error', '❌', job.error || 'Failed to fetch quotes');
                                
                                // Re-enable button on error
                                getQuotesBtn.disabled = false;
                                getQuotesBtn.innerHTML = `${_SVG_CANDLESTICK} GET QUOTES`;
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
                getQuotesBtn.innerHTML = `${_SVG_CANDLESTICK} GET QUOTES`;
            }
            
        } catch (error) {
            console.error('Error starting quote fetch:', error);
            showQuotesStatus('error', '❌', 'Error starting quote fetch. Please try again.');
            getQuotesBtn.disabled = false;
            getQuotesBtn.innerHTML = `${_SVG_CANDLESTICK} GET QUOTES`;
        }
    });
    
    // Place Order button functionality with job tracking
    placeOrderBtn.addEventListener('click', async function() {
        // Show custom confirmation modal
        showPlaceOrderConfirmModal();
    });
    
    // Setup confirmation modal buttons
    const confirmOrderBtn = document.getElementById('confirmOrderBtn');
    const cancelOrderBtn = document.getElementById('cancelOrderBtn');
    const placeOrderModal = document.getElementById('placeOrderModal');
    
    // Cancel button - close modal
    cancelOrderBtn.addEventListener('click', function() {
        placeOrderModal.style.display = 'none';
    });
    
    // Click outside modal to close
    placeOrderModal.addEventListener('click', function(e) {
        if (e.target === placeOrderModal) {
            placeOrderModal.style.display = 'none';
        }
    });
    
    // Escape key to close modal
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && placeOrderModal.style.display !== 'none') {
            placeOrderModal.style.display = 'none';
        }
    });
    
    // Confirm button - execute orders
    confirmOrderBtn.addEventListener('click', async function() {
        // Hide modal
        placeOrderModal.style.display = 'none';
        
        // Show loading status
        showOrderStatus('loading', '⏳', 'Starting order execution...');
        
        // Disable button during processing
        placeOrderBtn.disabled = true;
        placeOrderBtn.innerHTML = `${_SVG_LOADER_SPIN} Processing...`;
        
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
                                
                                // Update last order timestamp
                                updateLastAction('order');
                                
                                // Keep button disabled after successful execution
                                placeOrderBtn.innerHTML = `${_SVG_CHECK_CIRCLE} Orders Executed`;
                                placeOrderBtn.style.background = 'var(--green)';
                                
                            } else if (job.status === 'failed') {
                                clearInterval(pollInterval);
                                showOrderStatus('error', '❌', job.error || 'Order execution failed');
                                
                                // Re-enable button on error
                                placeOrderBtn.disabled = false;
                                placeOrderBtn.innerHTML = `${_SVG_ROCKET} PLACE ORDERS`;
                                placeOrderBtn.style.background = '';
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
                placeOrderBtn.innerHTML = `${_SVG_ROCKET} PLACE ORDERS`;
                placeOrderBtn.style.background = '';
            }
            
        } catch (error) {
            console.error('Error starting order execution:', error);
            showOrderStatus('error', '❌', 'Error starting order execution. Please try again.');
            placeOrderBtn.disabled = false;
            placeOrderBtn.innerHTML = `${_SVG_ROCKET} PLACE ORDERS`;
            placeOrderBtn.style.background = '';
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
            showTotpStatus('success', '🔐', `Session active until ${new Date(result.expires_at).toLocaleString()}`);
            
            totpInput.disabled = true;
            totpInput.style.background = '';
            totpInput.value = '******';
            
            checkTotpBtn.disabled = true;
            checkTotpBtn.innerHTML = `${_SVG_CHECK_CIRCLE} Session Active`;
            checkTotpBtn.style.background = 'var(--green)';
            checkTotpBtn.style.cursor = 'not-allowed';
        } else {
            totpInput.disabled = false;
            totpInput.style.background = '';
            totpInput.value = '';
            totpInput.placeholder = 'Enter 6-digit TOTP code';
            
            checkTotpBtn.disabled = false;
            checkTotpBtn.innerHTML = `${_SVG_SHIELD_CHECK} Check`;
            checkTotpBtn.style.background = '';
            checkTotpBtn.style.cursor = 'pointer';
            
            document.getElementById('totpStatus').style.display = 'none';
        }
        
    } catch (error) {
        console.error('Error checking session status:', error);
        const totpInput = document.getElementById('totpInput');
        const checkTotpBtn = document.getElementById('checkTotpBtn');
        
        totpInput.disabled = false;
        totpInput.style.background = '';
        checkTotpBtn.disabled = false;
        checkTotpBtn.innerHTML = `${_SVG_SHIELD_CHECK} Check`;
        checkTotpBtn.style.background = '';
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

function iconHtml(name, cls) {
    const svg = _ICON_MAP[name];
    if (svg) {
        if (cls) return `<span class="${cls}" style="display:inline-flex">${svg}</span>`;
        return svg;
    }
    return `<i data-lucide="${name}" ${cls ? `class="${cls}"` : ''}></i>`;
}

function refreshIcons(root) {
    if (typeof lucide !== 'undefined') {
        if (root) {
            lucide.createIcons({ nodes: root.querySelectorAll('[data-lucide]') });
        } else {
            lucide.createIcons();
        }
    }
}

const _s = (d, w = 14) => `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${w}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
const _SVG_PENCIL = _s('<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>');
const _SVG_FILE_TEXT = _s('<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>', 16);
const _SVG_REFRESH = _s('<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>');
const _SVG_LOADER = _s('<path d="M21 12a9 9 0 1 1-6.219-8.56"/>', 14);
const _SVG_CHECK_CIRCLE = _s('<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/>');
const _SVG_SHIELD_CHECK = _s('<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>');
const _SVG_ROCKET = _s('<path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>');
const _SVG_CANDLESTICK = _s('<path d="M9 5v4"/><rect width="4" height="6" x="7" y="9" rx="1"/><path d="M9 15v2"/><path d="M17 3v4"/><rect width="4" height="6" x="15" y="7" rx="1"/><path d="M17 13v3"/><path d="M3 3v18h18"/>');
const _SVG_RUPEE = _s('<path d="M6 3h12"/><path d="M6 8h12"/><path d="m6 13 8.5 8"/><path d="M6 13h3"/><path d="M9 13c6.667 0 6.667-10 0-10"/>');
const _SVG_CPU = _s('<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>');
const _SVG_X_CIRCLE = _s('<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>');
const _SVG_ALERT_TRI = _s('<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>');
const _SVG_INFO = _s('<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>');
const _SVG_DATABASE = _s('<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/>');
const _SVG_TRASH = _s('<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/>');
const _SVG_LOADER_SPIN = `<span class="spin" style="display:inline-flex">${_SVG_LOADER}</span>`;
const _ICON_MAP = {
    'pencil': _SVG_PENCIL, 'file-text': _SVG_FILE_TEXT, 'refresh-cw': _SVG_REFRESH,
    'loader-2': _SVG_LOADER, 'check-circle': _SVG_CHECK_CIRCLE, 'shield-check': _SVG_SHIELD_CHECK,
    'rocket': _SVG_ROCKET, 'candlestick-chart': _SVG_CANDLESTICK, 'indian-rupee': _SVG_RUPEE,
    'cpu': _SVG_CPU, 'x-circle': _SVG_X_CIRCLE, 'alert-triangle': _SVG_ALERT_TRI,
    'info': _SVG_INFO, 'database': _SVG_DATABASE
};

function showTotpStatus(type, icon, message) {
    const statusDiv = document.getElementById('totpStatus');
    const statusIcon = document.getElementById('statusIcon');
    const statusMessage = document.getElementById('statusMessage');
    
    statusDiv.className = `totp-status ${type}`;
    const iconMap = {'⏳': 'loader-2', '✅': 'check-circle', '❌': 'x-circle', '🔐': 'shield-check'};
    const lucideName = iconMap[icon] || 'info';
    statusIcon.innerHTML = iconHtml(lucideName, icon === '⏳' ? 'spin' : '');
    statusMessage.textContent = message;
    statusDiv.style.display = 'block';
}

// Show Place Order confirmation modal
function showPlaceOrderConfirmModal() {
    const modal = document.getElementById('placeOrderModal');
    if (modal) {
        modal.style.display = 'flex';
        // Focus on cancel button for safety (pressing Enter won't accidentally confirm)
        const cancelBtn = document.getElementById('cancelOrderBtn');
        if (cancelBtn) {
            setTimeout(() => cancelBtn.focus(), 100);
        }
    }
}

function showOrderStatus(type, icon, message) {
    const statusDiv = document.getElementById('orderStatus');
    const statusIcon = document.getElementById('orderStatusIcon');
    const statusMessage = document.getElementById('orderStatusMessage');
    
    statusDiv.className = `order-status ${type}`;
    const iconMap = {'⏳': 'loader-2', '✅': 'check-circle', '❌': 'x-circle'};
    const lucideName = iconMap[icon] || 'info';
    statusIcon.innerHTML = iconHtml(lucideName, icon === '⏳' ? 'spin' : '');
    statusMessage.textContent = message;
    statusDiv.style.display = 'block';
}

function showQuotesStatus(type, icon, message) {
    const statusDiv = document.getElementById('quotesStatus');
    const statusIcon = document.getElementById('quotesStatusIcon');
    const statusMessage = document.getElementById('quotesStatusMessage');
    
    statusDiv.className = `quotes-status ${type}`;
    const iconMap = {'⏳': 'loader-2', '✅': 'check-circle', '❌': 'x-circle', '⚠️': 'alert-triangle'};
    const lucideName = iconMap[icon] || 'info';
    statusIcon.innerHTML = iconHtml(lucideName, icon === '⏳' ? 'spin' : '');
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

// Fetch Scrip Master (NSE + BSE)
async function fetchScripMaster() {
    const btn = document.getElementById('fetchScripMasterBtn');
    if (!btn || btn.disabled) return;
    btn.disabled = true;
    const icon = btn.querySelector('svg');
    if (icon) icon.style.animation = 'spin 1s linear infinite';

    try {
        const resp = await fetch('/api/refresh_scrip_master', {
            method: 'POST',
            headers: getAuthHeaders()
        });
        const data = await resp.json();
        if (data.success) {
            showNotificationToast(`Scrip master refreshed — NSE: ${data.nse_count}, BSE: ${data.bse_count}`, 'success');
        } else {
            showNotificationToast(data.error || 'Failed to refresh scrip master', 'error');
        }
    } catch (e) {
        console.error('Scrip master fetch error:', e);
        showNotificationToast('Scrip master fetch failed', 'error');
    } finally {
        btn.disabled = false;
        if (icon) icon.style.animation = '';
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
        indicator.className = 'scheduled-task-status running';
        titleEl.textContent = 'Auto Fetch Running';
        messageEl.textContent = message;
        progressContainer.style.display = 'flex';
        timeEl.textContent = `Started: ${dateTimeStr}`;
        
        if (progress !== undefined) {
            progressBar.style.width = `${progress}%`;
            percentEl.textContent = `${progress}%`;
        }
    } else if (status === 'completed') {
        indicator.className = 'scheduled-task-status completed';
        titleEl.textContent = 'Auto Fetch Completed';
        messageEl.textContent = message;
        progressContainer.style.display = 'none';
        timeEl.textContent = `Completed: ${dateTimeStr}`;
    } else if (status === 'failed') {
        indicator.className = 'scheduled-task-status failed';
        titleEl.textContent = 'Auto Fetch Failed';
        messageEl.textContent = message;
        progressContainer.style.display = 'none';
        timeEl.textContent = `Failed: ${dateTimeStr}`;
    } else if (status === 'skipped') {
        indicator.className = 'scheduled-task-status skipped';
        titleEl.textContent = 'Auto Fetch Skipped';
        messageEl.textContent = message;
        progressContainer.style.display = 'none';
        timeEl.textContent = `Skipped: ${dateTimeStr}`;
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
async function restoreScheduledTaskStatus() {
    // First check if auto fetch is enabled - if not, don't restore/show anything
    const autoFetchEnabled = await checkAutoFetchEnabled();
    if (!autoFetchEnabled) {
        // Hide all auto fetch elements and return
        const indicator = document.getElementById('scheduledTaskIndicator');
        const autoScheduledInfo = document.getElementById('autoScheduledInfo');
        const scheduleEditor = document.getElementById('scheduleEditor');
        if (indicator) indicator.style.display = 'none';
        if (autoScheduledInfo) autoScheduledInfo.style.display = 'none';
        if (scheduleEditor) scheduleEditor.style.display = 'none';
        return;
    }
    
    const saved = localStorage.getItem('scheduledTaskStatus');
    if (saved) {
        try {
            const data = JSON.parse(saved);
            const indicator = document.getElementById('scheduledTaskIndicator');
            const titleEl = document.getElementById('scheduledTaskTitle');
            const messageEl = document.getElementById('scheduledTaskMessage');
            const timeEl = document.getElementById('scheduledTaskTime');
            const progressContainer = document.getElementById('scheduledProgressContainer');
            
            if (!indicator) {
                // If indicator doesn't exist yet, try to load config anyway to update display
                loadScheduledFetchConfig();
                return;
            }
            
            // Check if saved status is from today - if not, reset to waiting
            const today = new Date().toDateString();
            const savedDate = data.date || '';
            
            if (savedDate !== today) {
                // Previous day's status - reset to waiting for new day
                // Load current config to show correct time
                loadScheduledFetchConfig().then(config => {
                    if (config) {
                        const hour = config.hour || 12;
                        const minute = config.minute || 40;
                        const second = config.second || 0;
                        const period = hour >= 12 ? 'PM' : 'AM';
                        const displayHour = hour > 12 ? hour - 12 : (hour === 0 ? 12 : hour);
                        const timeStr = `${displayHour}:${String(minute).padStart(2, '0')}:${String(second).padStart(2, '0')} ${period}`;
                        
                        indicator.className = 'scheduled-task-status waiting';
                        titleEl.textContent = `Waiting for ${timeStr}`;
                        messageEl.textContent = 'Next auto-fetch scheduled';
                        progressContainer.style.display = 'none';
                        timeEl.textContent = '';
                        localStorage.removeItem('scheduledTaskStatus');  // Clear old status
                    } else {
                        // Fallback to default
                        indicator.className = 'scheduled-task-status waiting';
                        titleEl.textContent = 'Waiting for scheduled time';
                        messageEl.textContent = 'Next auto-fetch scheduled';
                        progressContainer.style.display = 'none';
                        timeEl.textContent = '';
                        localStorage.removeItem('scheduledTaskStatus');
                    }
                }).catch(() => {
                    // Fallback on error
                    indicator.className = 'scheduled-task-status waiting';
                    titleEl.textContent = 'Waiting for scheduled time';
                    messageEl.textContent = 'Next auto-fetch scheduled';
                    progressContainer.style.display = 'none';
                    timeEl.textContent = '';
                    localStorage.removeItem('scheduledTaskStatus');
                });
                return;
            }
            
            // Today's status - restore it
            const dateStr = new Date().toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
            
            if (data.status === 'completed') {
                indicator.className = 'scheduled-task-status completed';
                titleEl.textContent = 'Already Fetched Today';
                messageEl.textContent = data.message || 'Auto-fetch completed successfully';
                progressContainer.style.display = 'none';
                timeEl.textContent = `Already fetched: ${dateStr} at ${data.time}`;
            } else if (data.status === 'failed') {
                indicator.className = 'scheduled-task-status failed';
                titleEl.textContent = 'Auto Fetch Failed Today';
                messageEl.textContent = data.message;
                progressContainer.style.display = 'none';
                timeEl.textContent = `✗ Failed: ${dateStr} at ${data.time}`;
            } else if (data.status === 'skipped') {
                indicator.className = 'scheduled-task-status skipped';
                titleEl.textContent = 'Auto Fetch Skipped Today';
                messageEl.textContent = data.message;
                progressContainer.style.display = 'none';
                timeEl.textContent = `⚠ Skipped: ${dateStr} at ${data.time}`;
            }
            // If running, don't restore - will get fresh update from WebSocket
        } catch (e) {
            console.error('Error restoring scheduled task status:', e);
        }
    } else {
        // No saved status - load config and check if already fetched today from log
        loadScheduledFetchConfig().then(config => {
            const indicator = document.getElementById('scheduledTaskIndicator');
            const titleEl = document.getElementById('scheduledTaskTitle');
            const messageEl = document.getElementById('scheduledTaskMessage');
            const progressContainer = document.getElementById('scheduledProgressContainer');
            const timeEl = document.getElementById('scheduledTaskTime');
            
            if (config && indicator) {
                // If checkIfAlreadyFetchedToday didn't set status, show waiting
                if (indicator.className === 'scheduled-task-status' || !indicator.className.includes('completed')) {
                    const hour = config.hour || 12;
                    const minute = config.minute || 40;
                    const second = config.second || 0;
                    const period = hour >= 12 ? 'PM' : 'AM';
                    const displayHour = hour > 12 ? hour - 12 : (hour === 0 ? 12 : hour);
                    const timeStr = `${displayHour}:${String(minute).padStart(2, '0')}:${String(second).padStart(2, '0')} ${period}`;
                    
                    indicator.className = 'scheduled-task-status waiting';
                    if (titleEl) titleEl.textContent = `Waiting for ${timeStr}`;
                    if (messageEl) messageEl.textContent = 'Next auto-fetch scheduled';
                    if (progressContainer) progressContainer.style.display = 'none';
                    if (timeEl) timeEl.textContent = '';
                }
            }
        });
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

// ============================================================================
// SCHEDULED FETCH CONFIG MANAGEMENT
// ============================================================================

// Check if auto fetch is enabled (from server environment variable)
async function checkAutoFetchEnabled() {
    try {
        const response = await fetch('/api/auto_fetch_status');
        const result = await response.json();
        return result.success && result.auto_fetch_enabled;
    } catch (error) {
        console.error('Error checking auto fetch status:', error);
        return false;
    }
}

async function loadScheduledFetchConfig() {
    try {
        // First check if auto fetch is enabled
        const autoFetchEnabled = await checkAutoFetchEnabled();
        
        // Get all auto-fetch related elements
        const indicator = document.getElementById('scheduledTaskIndicator');
        const autoScheduledInfo = document.getElementById('autoScheduledInfo');
        const scheduleEditor = document.getElementById('scheduleEditor');
        
        if (!autoFetchEnabled) {
            // Hide ALL auto fetch UI elements when disabled
            if (indicator) {
                indicator.style.display = 'none';
            }
            if (autoScheduledInfo) {
                autoScheduledInfo.style.display = 'none';
            }
            if (scheduleEditor) {
                scheduleEditor.style.display = 'none';
            }
            console.log('Auto fetch is DISABLED (set AUTO_FETCH_ENABLED=true in .env to enable)');
            return null;
        }
        
        // Show elements if auto fetch is enabled
        if (indicator) {
            indicator.style.display = 'flex';
        }
        if (autoScheduledInfo) {
            autoScheduledInfo.style.display = 'block';
        }
        
        const response = await fetch('/api/scheduled_fetch_config');
        const result = await response.json();
        
        if (result.success && result.config) {
            const config = result.config;
            updateScheduledTimeDisplay(config);
            setupScheduleEditor(config);
            
            // Check if already fetched today from log file
            if (config.last_completion) {
                checkIfAlreadyFetchedToday(config.last_completion, config);
            }
            
            return config; // Return config for chaining
        } else {
            console.error('Failed to load config:', result.message);
            return null;
        }
    } catch (error) {
        console.error('Error loading scheduled fetch config:', error);
        return null;
    }
}

function checkIfAlreadyFetchedToday(lastCompletionStr, config) {
    try {
        const indicator = document.getElementById('scheduledTaskIndicator');
        const titleEl = document.getElementById('scheduledTaskTitle');
        const messageEl = document.getElementById('scheduledTaskMessage');
        const timeEl = document.getElementById('scheduledTaskTime');
        const progressContainer = document.getElementById('scheduledProgressContainer');
        
        if (!indicator || !titleEl) return;
        
        // Parse last completion time (format: "2026-01-02 09:15:31")
        const lastCompletion = new Date(lastCompletionStr.replace(' ', 'T') + '+05:30'); // IST
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        
        const lastCompletionDate = new Date(lastCompletion);
        lastCompletionDate.setHours(0, 0, 0, 0);
        
        // Check if last completion was today
        if (lastCompletionDate.getTime() === today.getTime()) {
            // Already fetched today
            const timeStr = lastCompletion.toLocaleTimeString('en-IN', { 
                hour: '2-digit', 
                minute: '2-digit', 
                second: '2-digit',
                hour12: true 
            });
            const dateStr = lastCompletion.toLocaleDateString('en-IN', { 
                day: '2-digit', 
                month: 'short' 
            });
            
            indicator.className = 'scheduled-task-status completed';
            titleEl.textContent = 'Already Fetched Today';
            messageEl.textContent = 'Auto-fetch completed successfully';
            if (progressContainer) progressContainer.style.display = 'none';
            if (timeEl) timeEl.textContent = `Already fetched: ${dateStr} at ${timeStr} IST`;
            
            // Save to localStorage
            localStorage.setItem('scheduledTaskStatus', JSON.stringify({
                status: 'completed',
                message: 'Auto-fetch completed successfully',
                time: timeStr,
                date: new Date().toDateString()
            }));
        }
    } catch (error) {
        console.error('Error checking last completion:', error);
    }
}

function updateScheduledTimeDisplay(config) {
    const displayEl = document.getElementById('scheduledTimeDisplay');
    if (!displayEl) return;
    
    const hour = config.hour || 12;
    const minute = config.minute || 40;
    const second = config.second || 0;
    const period = hour >= 12 ? 'PM' : 'AM';
    const displayHour = hour > 12 ? hour - 12 : (hour === 0 ? 12 : hour);
    
    displayEl.textContent = `${displayHour}:${String(minute).padStart(2, '0')}:${String(second).padStart(2, '0')} ${period} IST`;
    
    // Also update the scheduled task indicator title if it exists
    const titleEl = document.getElementById('scheduledTaskTitle');
    if (titleEl && titleEl.textContent.includes('Loading')) {
        titleEl.textContent = `Waiting for ${displayHour}:${String(minute).padStart(2, '0')}:${String(second).padStart(2, '0')} ${period}`;
        const messageEl = document.getElementById('scheduledTaskMessage');
        if (messageEl) {
            messageEl.textContent = 'Next auto-fetch scheduled';
        }
    }
}

function setupScheduleEditor(config) {
    const editBtn = document.getElementById('editScheduleBtn');
    const editor = document.getElementById('scheduleEditor');
    const saveBtn = document.getElementById('saveScheduleBtn');
    const cancelBtn = document.getElementById('cancelScheduleBtn');
    
    if (!editBtn || !editor) return;
    
    // Set initial values
    document.getElementById('scheduleHour').value = config.hour || 12;
    document.getElementById('scheduleMinute').value = config.minute || 40;
    document.getElementById('scheduleSecond').value = config.second || 0;
    document.getElementById('scheduleEnabled').checked = config.enabled !== false;
    document.getElementById('scheduleWeekdaysOnly').checked = config.weekdays_only !== false;
    
    // Toggle editor
    editBtn.addEventListener('click', () => {
        editor.style.display = editor.style.display === 'none' ? 'block' : 'none';
    });
    
    cancelBtn.addEventListener('click', () => {
        editor.style.display = 'none';
        // Reset to current config
        document.getElementById('scheduleHour').value = config.hour || 12;
        document.getElementById('scheduleMinute').value = config.minute || 40;
        document.getElementById('scheduleSecond').value = config.second || 0;
        document.getElementById('scheduleEnabled').checked = config.enabled !== false;
        document.getElementById('scheduleWeekdaysOnly').checked = config.weekdays_only !== false;
    });
    
    // Save config
    saveBtn.addEventListener('click', async () => {
        const hour = parseInt(document.getElementById('scheduleHour').value);
        const minute = parseInt(document.getElementById('scheduleMinute').value);
        const second = parseInt(document.getElementById('scheduleSecond').value);
        const enabled = document.getElementById('scheduleEnabled').checked;
        const weekdaysOnly = document.getElementById('scheduleWeekdaysOnly').checked;
        
        // Validate
        if (hour < 0 || hour > 23 || minute < 0 || minute > 59 || second < 0 || second > 59) {
            alert('Invalid time values. Hour: 0-23, Minute: 0-59, Second: 0-59');
            return;
        }
        
        saveBtn.disabled = true;
        saveBtn.textContent = '💾 Saving...';
        
        try {
            const response = await fetch('/api/scheduled_fetch_config', {
                method: 'PUT',
                headers: getAuthHeaders(),
                body: JSON.stringify({
                    hour,
                    minute,
                    second,
                    enabled,
                    weekdays_only: weekdaysOnly
                })
            });
            
            const result = await response.json();
            
            if (response.ok && result.success) {
                showNotificationToast(result.message, 'success');
                updateScheduledTimeDisplay({ hour, minute, second, enabled, weekdays_only: weekdaysOnly });
                editor.style.display = 'none';
                
                // Update the waiting message in scheduled task indicator
                const titleEl = document.getElementById('scheduledTaskTitle');
                if (titleEl) {
                    const period = hour >= 12 ? 'PM' : 'AM';
                    const displayHour = hour > 12 ? hour - 12 : (hour === 0 ? 12 : hour);
                    titleEl.textContent = `Waiting for ${displayHour}:${String(minute).padStart(2, '0')}:${String(second).padStart(2, '0')} ${period}`;
                }
            } else {
                showNotificationToast(result.message || 'Failed to update schedule', 'error');
            }
        } catch (error) {
            console.error('Error saving schedule config:', error);
            showNotificationToast('Error saving schedule configuration', 'error');
        } finally {
            saveBtn.disabled = false;
            saveBtn.textContent = '💾 Save';
        }
    });
}


// ============================================
// PE Analysis — Quarterly Results + Formula System
// ============================================

function _fyEndingYear(fy) {
    if (!fy) return null;
    const m = fy.match(/(\d{4})\s*-\s*(\d{2,4})/);
    if (m) {
        const startYr = parseInt(m[1]);
        const endPart = m[2];
        return endPart.length === 2 ? String(startYr + 1) : endPart;
    }
    const single = fy.match(/\d{4}/);
    return single ? single[0] : null;
}

let peAnalysisData = [];
let peCurrentPage = 1;
let peFormulas = [];
let peActiveFormulaIds = JSON.parse(localStorage.getItem('peActiveFormulaIds') || '[]');
let peActiveView = 'pending'; // 'pending' or 'reviewed'
let peTotalCount = 0;
let peTotalPages = 1;
let peServerLimit = 50;
let _peAbortCtrl = null;

// PE Multi-select filter state
const peFilterState = { year: new Set(), quarter: new Set(), sector: new Set(), exchange: new Set() };
let _peFiltersInitialized = false;

function _peInitDefaultFilters() {
    peFilterState.exchange.add('BSE');
    peFilterState.year.add(String(new Date().getFullYear()));
    peFilterState.quarter.add('Q4');
    _peFiltersInitialized = true;
}

function _updatePEViewHeader() {
    const titleEl = document.getElementById('peAnalysisTitle');
    if (titleEl) {
        const prefix = peActiveView === 'reviewed' ? 'PE Reviewed' : 'PE Pending';
        const qtrs = [...peFilterState.quarter].sort().join(', ');
        const yrs = [...peFilterState.year].sort().map(y => 'FY' + String(y).slice(-2)).join(', ');
        let sub = '';
        if (qtrs) sub += qtrs + ' ';
        if (yrs) sub += yrs + ' ';
        sub += sub ? 'Results' : 'Quarterly Results';
        titleEl.innerHTML = `${prefix} &mdash; ${sub}`;
    }
}

function _updatePETitle() {
    _updatePEViewHeader();
}

// PE Column Visibility
const PE_COLUMNS = [
    { key: 'date', label: 'Date' },
    { key: 'exch', label: 'Exchange' },
    { key: 'quarter', label: 'Quarter' },
    { key: 'year', label: 'Year' },
    { key: 'qtreps', label: 'Qtr EPS' },
    { key: 'epsqoq', label: 'EPS Q/Q' },
    { key: 'epsyoy', label: 'EPS Y/Y' },
    { key: 'cumeps', label: 'Cum. EPS' },
    { key: 'cumprevfy', label: 'Cum. Prev FY' },
    { key: 'prevfyeps', label: 'Prev FY EPS' },
    { key: 'fyeps', label: 'FY EPS (Est.)' },
    { key: 'cmp', label: 'CMP' },
    { key: 'pe', label: 'PE' },
    { key: 'sector', label: 'Sector' },
    { key: 'remark', label: 'Remark' },
    { key: 'comments', label: 'Comments' },
    { key: 'file', label: 'File' },
];
let _peVisibleCols = null;

function _peLoadColVisibility() {
    try {
        const saved = localStorage.getItem('peVisibleColumns');
        if (saved) {
            const set = new Set(JSON.parse(saved));
            const allKeys = new Set(PE_COLUMNS.map(c => c.key));
            for (const k of allKeys) {
                if (!set.has(k) && !localStorage.getItem('peCol_hidden_' + k)) set.add(k);
            }
            return set;
        }
    } catch (e) {}
    return new Set(PE_COLUMNS.map(c => c.key));
}

function _peSaveColVisibility() {
    localStorage.setItem('peVisibleColumns', JSON.stringify([..._peVisibleCols]));
}

function peApplyColumnVisibility() {
    if (!_peVisibleCols) _peVisibleCols = _peLoadColVisibility();
    let css = '';
    for (const col of PE_COLUMNS) {
        if (!_peVisibleCols.has(col.key)) {
            css += `.pvc-${col.key} { display: none !important; }\n`;
        }
    }
    let styleEl = document.getElementById('peColVisStyle');
    if (!styleEl) {
        styleEl = document.createElement('style');
        styleEl.id = 'peColVisStyle';
        document.head.appendChild(styleEl);
    }
    styleEl.textContent = css;
}

function peInitColumnsToggle() {
    if (!_peVisibleCols) _peVisibleCols = _peLoadColVisibility();
    const dd = document.getElementById('peColumnsDropdown');
    if (!dd) return;
    let html = '<div class="pe-col-search"><input type="text" id="peColSearchInput" placeholder="Search columns..." autocomplete="off"></div>';
    html += '<div class="pe-col-list">';
    for (const col of PE_COLUMNS) {
        const checked = _peVisibleCols.has(col.key);
        html += `<label class="pe-ms-option pe-col-item${checked ? ' checked' : ''}" data-col-label="${col.label.toLowerCase()}">
            <input type="checkbox" ${checked ? 'checked' : ''} onchange="peToggleColumn('${col.key}', this.checked)">
            <span>${col.label}</span>
        </label>`;
    }
    html += '</div>';
    dd.innerHTML = html;
    const searchInput = document.getElementById('peColSearchInput');
    if (searchInput) {
        searchInput.addEventListener('input', () => {
            const q = searchInput.value.toLowerCase();
            dd.querySelectorAll('.pe-col-item').forEach(item => {
                item.style.display = item.dataset.colLabel.includes(q) ? '' : 'none';
            });
        });
        searchInput.addEventListener('click', e => e.stopPropagation());
    }
}

function peToggleColumn(key, visible) {
    if (!_peVisibleCols) _peVisibleCols = _peLoadColVisibility();
    if (visible) {
        _peVisibleCols.add(key);
        localStorage.removeItem('peCol_hidden_' + key);
    } else {
        _peVisibleCols.delete(key);
        localStorage.setItem('peCol_hidden_' + key, '1');
    }
    _peSaveColVisibility();
    peApplyColumnVisibility();
    peInitColumnsToggle();
}

function _positionPeDropdown(wrap) {
    const btn = wrap.querySelector('.pe-multiselect-btn');
    const dd = wrap.querySelector('.pe-multiselect-dropdown');
    if (!btn || !dd) return;
    const rect = btn.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom - 8;
    const ddHeight = Math.min(dd.scrollHeight || 260, 260);
    if (spaceBelow < ddHeight && rect.top > ddHeight) {
        dd.style.top = (rect.top - ddHeight - 4) + 'px';
    } else {
        dd.style.top = (rect.bottom + 4) + 'px';
    }
    const spaceRight = window.innerWidth - rect.left;
    if (spaceRight < 200) {
        dd.style.left = 'auto';
        dd.style.right = (window.innerWidth - rect.right) + 'px';
    } else {
        dd.style.left = rect.left + 'px';
        dd.style.right = 'auto';
    }
}

function peInitMultiselects() {
    document.querySelectorAll('.pe-multiselect').forEach(wrap => {
        const btn = wrap.querySelector('.pe-multiselect-btn');
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const wasOpen = wrap.classList.contains('open');
            document.querySelectorAll('.pe-multiselect.open').forEach(el => el.classList.remove('open'));
            if (!wasOpen) {
                wrap.classList.add('open');
                _positionPeDropdown(wrap);
            }
        });
    });
    document.addEventListener('click', () => {
        document.querySelectorAll('.pe-multiselect.open').forEach(el => el.classList.remove('open'));
    });
    const scrollParent = document.querySelector('.content-area') || document.querySelector('.analytics-view');
    if (scrollParent) {
        scrollParent.addEventListener('scroll', () => {
            document.querySelectorAll('.pe-multiselect.open').forEach(el => el.classList.remove('open'));
        }, { passive: true });
    }
    document.querySelectorAll('.pe-multiselect-dropdown').forEach(dd => {
        dd.addEventListener('click', e => e.stopPropagation());
    });
    const clearBtn = document.getElementById('peClearFiltersBtn');
    if (clearBtn) clearBtn.addEventListener('click', () => {
        peFilterState.year.clear(); peFilterState.quarter.clear(); peFilterState.exchange.clear();
        _peFiltersInitialized = true;
        peCurrentPage = 1;
        pePopulateFilterDropdowns();
        _updatePETitle();
        loadPEAnalysis();
    });
    const clearBtn2 = document.getElementById('peClearTier2Btn');
    if (clearBtn2) clearBtn2.addEventListener('click', () => {
        peFilterState.sector.clear();
        peCurrentPage = 1;
        _peCalClear();
        const searchInput = document.getElementById('peSymbolFilter');
        if (searchInput) searchInput.value = '';
        _peFiltersInitialized = true;
        pePopulateFilterDropdowns();
        _updatePETitle();
        loadPEAnalysis();
    });
}

// ---- Date Range Calendar Picker ----
const _peCal = { viewYear: null, viewMonth: null, start: null, end: null, picking: 'start' };

function peInitDateRangePicker() {
    const now = new Date();
    _peCal.viewYear = now.getFullYear();
    _peCal.viewMonth = now.getMonth();
    _peCalRender();
}

function _peCalRender() {
    const dd = document.getElementById('peDateDropdown');
    if (!dd) return;
    const months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    const dows = ['Su','Mo','Tu','We','Th','Fr','Sa'];
    const y = _peCal.viewYear, m = _peCal.viewMonth;
    const firstDay = new Date(y, m, 1).getDay();
    const daysInMonth = new Date(y, m + 1, 0).getDate();
    const daysInPrev = new Date(y, m, 0).getDate();
    const today = new Date(); today.setHours(0,0,0,0);

    let html = `<div class="pe-cal-header">
        <button type="button" onclick="_peCalNav(-1)" title="Previous month">&#8249;</button>
        <span class="pe-cal-title">${months[m]} ${y}</span>
        <button type="button" onclick="_peCalNav(1)" title="Next month">&#8250;</button>
    </div><div class="pe-cal-grid">`;
    for (const d of dows) html += `<span class="pe-cal-dow">${d}</span>`;

    for (let i = 0; i < firstDay; i++) {
        const day = daysInPrev - firstDay + 1 + i;
        const dt = new Date(y, m - 1, day); dt.setHours(0,0,0,0);
        html += `<button type="button" class="pe-cal-day other-month ${_peCalDayClass(dt, today)}" data-date="${_peCalFmt(dt)}">${day}</button>`;
    }
    for (let d = 1; d <= daysInMonth; d++) {
        const dt = new Date(y, m, d); dt.setHours(0,0,0,0);
        html += `<button type="button" class="pe-cal-day ${_peCalDayClass(dt, today)}" data-date="${_peCalFmt(dt)}">${d}</button>`;
    }
    const totalCells = firstDay + daysInMonth;
    const remaining = (7 - (totalCells % 7)) % 7;
    for (let i = 1; i <= remaining; i++) {
        const dt = new Date(y, m + 1, i); dt.setHours(0,0,0,0);
        html += `<button type="button" class="pe-cal-day other-month ${_peCalDayClass(dt, today)}" data-date="${_peCalFmt(dt)}">${i}</button>`;
    }
    html += '</div>';

    if (_peCal.start || _peCal.end) {
        const startStr = _peCal.start ? _peCalDisplayFmt(_peCal.start) : '—';
        const endStr = _peCal.end ? _peCalDisplayFmt(_peCal.end) : startStr;
        html += `<div class="pe-cal-footer">
            <span class="pe-cal-range-text">${startStr}  →  ${endStr}</span>
        </div>`;
    }
    dd.innerHTML = html;

    dd.querySelectorAll('.pe-cal-day').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            _peCalPickDate(btn.dataset.date);
        });
    });
}

function _peCalFmt(d) {
    return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
}
function _peCalDisplayFmt(dateStr) {
    const d = new Date(dateStr + 'T00:00:00');
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}

function _peCalDayClass(dt, today) {
    let cls = '';
    if (dt.getTime() === today.getTime()) cls += ' today';
    if (_peCal.start && _peCal.end) {
        const s = new Date(_peCal.start + 'T00:00:00'), e = new Date(_peCal.end + 'T00:00:00');
        s.setHours(0,0,0,0); e.setHours(0,0,0,0);
        if (dt >= s && dt <= e) cls += ' in-range';
        if (_peCalFmt(dt) === _peCal.start) cls += ' range-start';
        if (_peCalFmt(dt) === _peCal.end) cls += ' range-end';
    } else if (_peCal.start && _peCalFmt(dt) === _peCal.start) {
        cls += ' range-start range-end';
    }
    return cls;
}

function _peCalNav(dir) {
    _peCal.viewMonth += dir;
    if (_peCal.viewMonth < 0) { _peCal.viewMonth = 11; _peCal.viewYear--; }
    if (_peCal.viewMonth > 11) { _peCal.viewMonth = 0; _peCal.viewYear++; }
    _peCalRender();
}

function _peCalPickDate(dateStr) {
    if (_peCal.picking === 'start' || !_peCal.start) {
        _peCal.start = dateStr;
        _peCal.end = null;
        _peCal.picking = 'end';
        _peCalRender();
    } else {
        if (dateStr < _peCal.start) {
            _peCal.start = dateStr;
            _peCalRender();
            return;
        }
        _peCal.end = dateStr;
        _peCal.picking = 'start';
        _peCalRender();
        _peCalApply();
    }
}

function _peCalClear() {
    _peCal.start = null;
    _peCal.end = null;
    _peCal.picking = 'start';
    const df = document.getElementById('peDateFrom'); if (df) df.value = '';
    const dt = document.getElementById('peDateTo'); if (dt) dt.value = '';
    _peCalUpdateLabel();
    _peCalRender();
    peCurrentPage = 1;
    loadPEAnalysis();
}

function _peCalApply() {
    const df = document.getElementById('peDateFrom');
    const dt = document.getElementById('peDateTo');
    if (df) df.value = _peCal.start || '';
    if (dt) dt.value = _peCal.end || _peCal.start || '';
    _peCalUpdateLabel();
    document.getElementById('peDateRangeWrap')?.classList.remove('open');
    peCurrentPage = 1;
    loadPEAnalysis();
}

function _peCalUpdateLabel() {
    const label = document.getElementById('peDateRangeLabel');
    const btn = document.getElementById('peDateRangeBtn');
    if (!label || !btn) return;
    const df = document.getElementById('peDateFrom')?.value;
    const dt = document.getElementById('peDateTo')?.value;

    let clearSpan = btn.querySelector('.pe-cal-btn-clear');
    if (df || dt) {
        const text = (df && dt) ? _peCalDisplayFmt(df) + ' – ' + _peCalDisplayFmt(dt)
            : df ? 'From ' + _peCalDisplayFmt(df) : 'Date Range';
        label.textContent = text;
        if (!clearSpan) {
            clearSpan = document.createElement('span');
            clearSpan.className = 'pe-cal-btn-clear';
            clearSpan.innerHTML = '&times;';
            clearSpan.title = 'Clear date filter';
            clearSpan.addEventListener('click', (e) => {
                e.stopPropagation();
                _peCalClear();
            });
            btn.appendChild(clearSpan);
        }
    } else {
        label.textContent = 'Date Range';
        if (clearSpan) clearSpan.remove();
    }
}

function pePopulateFilterDropdowns() {
    let years, quarters, sectors, exchanges;
    if (_peServerFilterOptions) {
        years = new Set(_peServerFilterOptions.years || []);
        quarters = new Set(_peServerFilterOptions.quarters || []);
        sectors = new Set(_peServerFilterOptions.sectors || []);
        exchanges = new Set(_peServerFilterOptions.exchanges || []);
    } else {
        years = new Set(); quarters = new Set(); sectors = new Set(); exchanges = new Set();
        for (const r of peAnalysisData) {
            const fy = r.financial_year || '';
            const ym = _fyEndingYear(fy);
            if (ym) years.add(ym);
            if (r.quarter) quarters.add(r.quarter.toUpperCase());
            if (r.sector) sectors.add(r.sector);
            if (r.exchange) exchanges.add(r.exchange);
        }
    }

    if (!_peFiltersInitialized) {
        if (exchanges.has('BSE')) peFilterState.exchange.add('BSE');
        const curEndYear = String(new Date().getFullYear());
        if (years.has(curEndYear)) peFilterState.year.add(curEndYear);
        if (quarters.has('Q4')) peFilterState.quarter.add('Q4');
        _peFiltersInitialized = true;
    }

    function buildDropdown(filterId, values, stateKey, showSearch, labelFn) {
        const wrap = document.getElementById(filterId);
        if (!wrap) return;
        const dd = wrap.querySelector('.pe-multiselect-dropdown');
        if (!dd) return;
        const badge = wrap.querySelector('.pe-ms-badge');
        const sorted = [...values].sort();
        let html = '';
        if (showSearch && sorted.length > 6) {
            html += `<div class="pe-ms-search"><input type="text" placeholder="Search..." oninput="peFilterDropdownSearch(this)"></div>`;
        }
        for (const val of sorted) {
            const checked = peFilterState[stateKey].has(val);
            const display = labelFn ? labelFn(val) : val;
            html += `<label class="pe-ms-option${checked ? ' checked' : ''}" data-val="${val}">
                <input type="checkbox" ${checked ? 'checked' : ''} onchange="peToggleFilter('${stateKey}','${val.replace(/'/g, "\\'")}',this.checked)">
                <span>${display}</span>
            </label>`;
        }
        dd.innerHTML = html;
        for (const v of peFilterState[stateKey]) { if (!values.has(v)) peFilterState[stateKey].delete(v); }
        const count = peFilterState[stateKey].size;
        badge.style.display = count > 0 ? 'inline-block' : 'none';
        badge.textContent = count;
    }

    buildDropdown('peYearFilter', years, 'year', false, y => 'FY' + String(y).slice(-2));
    buildDropdown('peQuarterFilter', quarters, 'quarter', false);
    buildDropdown('peSectorFilter', sectors, 'sector', true);
    buildDropdown('peExchangeFilter', exchanges, 'exchange', false);

    const tier1Active = peFilterState.year.size + peFilterState.quarter.size + peFilterState.exchange.size > 0;
    const clearBtn = document.getElementById('peClearFiltersBtn');
    if (clearBtn) clearBtn.style.display = tier1Active ? 'flex' : 'none';

    const dateActive = !!(document.getElementById('peDateFrom')?.value || document.getElementById('peDateTo')?.value);
    const searchActive = !!(document.getElementById('peSymbolFilter')?.value?.trim());
    const tier2Active = peFilterState.sector.size > 0 || dateActive || searchActive;
    const clearBtn2 = document.getElementById('peClearTier2Btn');
    if (clearBtn2) clearBtn2.style.display = tier2Active ? 'flex' : 'none';
}

function peToggleFilter(key, val, checked) {
    if (checked) peFilterState[key].add(val); else peFilterState[key].delete(val);
    peCurrentPage = 1;
    pePopulateFilterDropdowns();
    _updatePETitle();
    loadPEAnalysis();
}

function peFilterDropdownSearch(input) {
    const q = input.value.toLowerCase();
    const options = input.closest('.pe-multiselect-dropdown').querySelectorAll('.pe-ms-option');
    options.forEach(opt => {
        opt.style.display = opt.dataset.val.toLowerCase().includes(q) ? '' : 'none';
    });
}

function peClassFor(pe) {
    if (!pe) return '';
    if (pe < 15) return 'pe-low';
    if (pe < 30) return 'pe-mid';
    return 'pe-high';
}

function evalFormulaExpr(expr, quartersEps) {
    if (!expr) return null;
    if (expr === 'FY') return quartersEps['FY'] || null;
    const vars = {
        PQ4: quartersEps['PQ4'], PQ3: quartersEps['PQ3'], PQ2: quartersEps['PQ2'], PQ1: quartersEps['PQ1'],
        PFY: quartersEps['PFY'], PN9: quartersEps['PN9'], PN6: quartersEps['PN6'], PN3: quartersEps['PN3'],
        N9: quartersEps['N9'], N6: quartersEps['N6'], N3: quartersEps['N3'],
        Q4: quartersEps['Q4'], Q3: quartersEps['Q3'], Q2: quartersEps['Q2'], Q1: quartersEps['Q1'],
    };
    let safe = expr;
    for (const [k, v] of Object.entries(vars)) {
        safe = safe.replace(new RegExp(k, 'g'), v != null ? String(v) : 'NaN');
    }
    if (!/^[\d\s+\-*/().NaN]+$/.test(safe) || safe.includes('NaN')) return null;
    try { const v = new Function('return ' + safe)(); return isFinite(v) ? +v.toFixed(2) : null; }
    catch { return null; }
}

function getFormulaExprForQuarter(formula, quarter) {
    const q = (quarter || '').toUpperCase();
    if (q === 'Q1') return formula.q1_expr;
    if (q === 'Q2') return formula.q2_expr;
    if (q === 'Q3') return formula.q3_expr;
    if (q === 'Q4' || q === 'FY') return formula.q4_expr;
    return null;
}

async function loadPeFormulas() {
    try {
        const resp = await fetch('/api/pe_formulas');
        const data = await resp.json();
        if (data.success) {
            peFormulas = data.formulas;
            const defaultF = peFormulas.find(f => f.is_default);
            if (defaultF && !peActiveFormulaIds.includes(defaultF.id)) {
                peActiveFormulaIds = [defaultF.id, ...peActiveFormulaIds.filter(id => id !== defaultF.id)];
                localStorage.setItem('peActiveFormulaIds', JSON.stringify(peActiveFormulaIds));
            }
            peActiveFormulaIds = peActiveFormulaIds.filter(id => peFormulas.some(f => f.id === id));
            renderPeFormulaList();
        }
    } catch (e) { console.error('Error loading PE formulas:', e); }
}

function renderPeFormulaList() {
    const list = document.getElementById('peFormulaList');
    if (!list) return;
    list.innerHTML = peFormulas.map(f => {
        const checked = peActiveFormulaIds.includes(f.id) ? 'checked' : '';
        const disabled = f.is_default ? 'disabled' : '';
        const delBtn = f.is_default ? '' : `<button class="pe-formula-del-btn" onclick="deletePeFormula(${f.id})" title="Delete">&times;</button>`;
        const exprs = `Q1: ${f.q1_expr}  ·  Q2: ${f.q2_expr}  ·  Q3: ${f.q3_expr}  ·  Q4: ${f.q4_expr}`;
        return `<div class="pe-formula-item">
            <input type="checkbox" value="${f.id}" ${checked} ${disabled} onchange="togglePeFormula(${f.id}, this.checked)">
            <div class="pe-formula-item-info">
                <div class="pe-formula-item-name">${f.name}${f.is_default ? ' <span style="font-size:0.6rem;color:#888;font-weight:400;">(built-in)</span>' : ''}</div>
                <div class="pe-formula-item-expr">${exprs}</div>
            </div>
            ${delBtn}
        </div>`;
    }).join('');
}

function togglePeFormula(id, checked) {
    if (checked && !peActiveFormulaIds.includes(id)) peActiveFormulaIds.push(id);
    if (!checked) peActiveFormulaIds = peActiveFormulaIds.filter(i => i !== id);
    localStorage.setItem('peActiveFormulaIds', JSON.stringify(peActiveFormulaIds));
    renderPEAnalysis();
}

async function deletePeFormula(id) {
    if (!confirm('Delete this formula?')) return;
    try {
        const resp = await fetch(`/api/pe_formulas/${id}`, { method: 'DELETE' });
        const data = await resp.json();
        if (data.success) {
            peActiveFormulaIds = peActiveFormulaIds.filter(i => i !== id);
            localStorage.setItem('peActiveFormulaIds', JSON.stringify(peActiveFormulaIds));
            await loadPeFormulas();
            renderPEAnalysis();
        }
    } catch (e) { console.error('Delete formula error:', e); }
}

async function createPeFormula(name, q1, q2, q3, q4) {
    const resp = await fetch('/api/pe_formulas', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, q1_expr: q1, q2_expr: q2, q3_expr: q3, q4_expr: q4 })
    });
    return await resp.json();
}

async function loadQuarterlyResults() {
    await loadPEAnalysis();
}

function _buildPEQueryParams(fetchCmp = false) {
    const params = new URLSearchParams();
    params.set('valuation_filter', peActiveView === 'reviewed' ? 'reviewed' : 'pending');
    params.set('fetch_cmp', fetchCmp);

    const limit = parseInt(document.getElementById('peShowLimit')?.value || '50', 10);
    peServerLimit = limit > 0 ? limit : 0;
    if (peServerLimit > 0) {
        params.set('limit', peServerLimit);
        params.set('page', peCurrentPage);
    }

    const search = (document.getElementById('peSymbolFilter')?.value || '').trim();
    if (search) params.set('search', search);

    if (peFilterState.year.size > 0) params.set('year', [...peFilterState.year].join(','));
    if (peFilterState.quarter.size > 0) params.set('quarter', [...peFilterState.quarter].join(','));
    if (peFilterState.exchange.size > 0) params.set('exchange', [...peFilterState.exchange].join(','));
    if (peFilterState.sector.size > 0) params.set('sector', [...peFilterState.sector].join(','));

    const dateFrom = document.getElementById('peDateFrom')?.value;
    const dateTo = document.getElementById('peDateTo')?.value;
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);

    if (fetchCmp && peAnalysisData.length > 0) {
        const syms = peAnalysisData.map(r => r.stock_symbol).filter(Boolean);
        if (syms.length > 0) params.set('symbols', syms.join(','));
    }

    return params;
}

async function loadPEAnalysis(fetchCmp = false) {
    if (_peAbortCtrl) _peAbortCtrl.abort();
    _peAbortCtrl = new AbortController();
    const signal = _peAbortCtrl.signal;

    const tbody = document.getElementById('peAnalysisBody');
    const emptyMsg = document.getElementById('peAnalysisEmpty');
    if (tbody) {
        tbody.innerHTML = `<tr><td colspan="20" style="text-align:center;padding:40px 0;color:#94a3b8;">
            <span class="pe-ext-spinner" style="display:inline-block;width:22px;height:22px;border-width:3px;vertical-align:middle;margin-right:10px;"></span>
            Loading ${peActiveView === 'reviewed' ? 'reviewed' : 'pending'} data&hellip;</td></tr>`;
    }
    if (emptyMsg) emptyMsg.style.display = 'none';

    try {
        const params = _buildPEQueryParams(fetchCmp);
        const formulaP = peFormulas.length === 0 ? loadPeFormulas() : null;
        const resp = await fetch(`/api/pe_analysis?${params.toString()}`, { signal });
        const data = await resp.json();
        if (formulaP) await formulaP;
        if (data.success && data.results) {
            peAnalysisData = data.results;
            peTotalCount = data.total_count || data.results.length;
            peTotalPages = data.total_pages || 1;
            if (peCurrentPage > peTotalPages) peCurrentPage = peTotalPages;
            if (peCurrentPage < 1) peCurrentPage = 1;
            renderPEAnalysis();
            _updatePETitle();
        }
        if (fetchCmp) {
            if (data.cmp_error) {
                showNotificationToast(data.cmp_error, 'warning');
            } else if (data.cmp_fetched) {
                showNotificationToast(`CMP updated for ${data.cmp_fetched} stocks`, 'success');
            }
        }
    } catch (e) {
        if (e.name === 'AbortError') return;
        console.error('Error loading PE analysis:', e);
        showNotificationToast('Failed to load PE analysis: ' + (e.message || e), 'error');
    }
}

async function loadPEFilterOptions() {
    try {
        const vf = peActiveView === 'reviewed' ? 'reviewed' : 'pending';
        const resp = await fetch(`/api/pe_analysis/filter_options?valuation_filter=${vf}`);
        const data = await resp.json();
        if (data.success) {
            _peServerFilterOptions = data;
            pePopulateFilterDropdowns();
        }
    } catch (e) { console.error('Error loading PE filter options:', e); }
}
let _peServerFilterOptions = null;

function _getVisiblePESymbols() {
    return peAnalysisData.map(r => r.stock_symbol).filter(Boolean);
}

function renderPEAnalysis() {
    const tbody = document.getElementById('peAnalysisBody');
    const emptyMsg = document.getElementById('peAnalysisEmpty');
    if (!tbody) return;

    let filtered = peAnalysisData;

    if (filtered.length === 0) {
        tbody.innerHTML = '';
        emptyMsg.style.display = 'block';
        document.getElementById('peResultCount').textContent = '';
        document.querySelectorAll('.pe-pagination').forEach(w => w.style.display = 'none');
        return;
    }
    emptyMsg.style.display = 'none';

    const totalFiltered = peTotalCount;
    const peLimit = peServerLimit;
    document.getElementById('peResultCount').textContent = peLimit > 0 && peTotalPages > 1
        ? `${(peCurrentPage - 1) * peLimit + 1}–${Math.min(peCurrentPage * peLimit, totalFiltered)} of ${totalFiltered} stocks`
        : `${totalFiltered} stocks`;
    renderPEPagination(peTotalPages, totalFiltered, peLimit);

    const fmt = v => (v !== null && v !== undefined && v !== '-' && v !== '') ? Number(v).toLocaleString('en-IN', {maximumFractionDigits: 2}) : '';
    const fmtCurrency = v => (v !== null && v !== undefined && v !== '' && !isNaN(v)) ? Number(v).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '';

    const activeFormulas = peFormulas.filter(f => peActiveFormulaIds.includes(f.id));
    if (activeFormulas.length === 0 && peFormulas.length > 0) {
        const def = peFormulas.find(f => f.is_default);
        if (def) activeFormulas.push(def);
    }
    const rowCount = Math.max(activeFormulas.length, 1);

    let html = '';
    for (const r of filtered) {
        const qtrEps = r.qtr_eps;
        const cmp = r.cmp;
        const dateSource = r.announcement_date || r.updated_at;
        const _dt = dateSource ? new Date(dateSource) : null;
        const updated = _dt ? `<span style="white-space:nowrap">${_dt.toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'numeric'})}</span><br><small style="color:#888;white-space:nowrap">${_dt.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',hour12:true})}</small>` : '';
        const basisBadge = (r.eps_basis === 'S' && qtrEps != null && qtrEps !== '') ? '<span style="font-size:0.65rem;background:#854d0e;color:#fde68a;padding:1px 5px;border-radius:3px;margin-left:4px;" title="Standalone only — no consolidated EPS available">S</span>' : '';
        const fy = r.financial_year || '';
        const yearVal = _fyEndingYear(fy) || fy;
        const yearDisplay = yearVal && yearVal.length === 4 ? 'FY' + yearVal.slice(-2) : fy;
        const sym = r.stock_symbol || '';
        const fileLink = r.source_pdf_url
            ? `<a href="${r.source_pdf_url}" target="_blank" rel="noopener" title="${r.source_pdf_url}" style="color:#60a5fa;">${_SVG_FILE_TEXT}</a>`
            : '';
        const stockCell = (r.exchange === 'BSE' && r.company_name)
            ? `<strong>${r.company_name}</strong><br><small style="color:#888">${sym}</small>`
            : `<strong>${sym}</strong>${r.company_name ? '<br><small style="color:#888">' + r.company_name + '</small>' : ''}`;

        const extStatus = r.extraction_status || 'completed';
        const isFailed = extStatus === 'failed';
        const isQueued = extStatus === 'queued';
        const isProcessing = extStatus === 'processing';
        const isCompleted = extStatus === 'completed';
        const isPending = isFailed || isQueued || isProcessing;
        let extBadge = '';
        if (isFailed) {
            extBadge = `<span class="pe-ext-badge pe-ext-failed" title="${(r.extraction_error || 'Extraction failed').replace(/"/g, '&quot;')}">FAILED</span>`;
        } else if (isQueued) {
            extBadge = '<span class="pe-ext-badge pe-ext-queued">QUEUED</span>';
        } else if (isProcessing) {
            extBadge = '<span class="pe-ext-badge pe-ext-processing"><span class="pe-ext-spinner"></span> EXTRACTING</span>';
        } else if (isCompleted) {
            extBadge = '<span class="pe-ext-badge pe-ext-success">SUCCESS</span>';
        }
        const hasFile = !!r.source_pdf_url;
        const retryBtn = (isFailed && hasFile) ? `<button class="pe-retry-btn" data-symbol="${sym}" onclick="peRetryExtraction('${sym}', this)" title="Retry extraction">${_SVG_REFRESH} Retry</button>` : '';

        const qe = r.quarters_eps || {};
        const q = (r.quarter || '').toUpperCase();

        // Current FY cumulative EPS (Q1 has no meaningful cumulative — it's just Q1 itself)
        let cumEpsVal = null, cumLabel = '';
        if (q === 'Q4' || q === 'FY') { cumEpsVal = qe['N12'] || qe['FY']; cumLabel = 'N12'; }
        else if (q === 'Q3') { cumEpsVal = qe['N9']; cumLabel = 'N9'; }
        else if (q === 'Q2') { cumEpsVal = qe['N6']; cumLabel = 'N6'; }
        const cumCell = cumEpsVal != null
            ? `${fmt(cumEpsVal)}<br><small style="color:#888">${cumLabel}</small>`
            : (q === 'Q1' ? '<small style="color:#555">—</small>' : (cumLabel ? `<small style="color:#555">${cumLabel}</small>` : ''));

        // EPS Q-on-Q: previous quarter's EPS
        const qoqMap = { Q2: 'Q1', Q3: 'Q2', Q4: 'Q3', Q1: 'PQ4' };
        const prevQKey = qoqMap[q];
        const epsQoQ = prevQKey ? qe[prevQKey] : null;
        const qoqLabel = prevQKey || '';
        const qoqCell = epsQoQ != null
            ? `${fmt(epsQoQ)}<br><small style="color:#888">${qoqLabel}</small>`
            : (qoqLabel ? `<small style="color:#555">${qoqLabel}</small>` : '');

        // EPS Y-on-Y: same quarter from previous year
        const yoyKey = q ? `P${q}` : null;
        const epsYoY = yoyKey ? qe[yoyKey] : null;
        const yoyLabel = yoyKey || '';
        const yoyCell = epsYoY != null
            ? `${fmt(epsYoY)}<br><small style="color:#888">Prev ${q}</small>`
            : (yoyLabel ? `<small style="color:#555">Prev ${q}</small>` : '');

        // Cumulative EPS from previous FY (Y-on-Y comparison; Q1 has no cumulative to compare)
        let cumPrevVal = null, cumPrevLabel = '';
        if (q === 'Q4' || q === 'FY') { cumPrevVal = qe['PFY']; cumPrevLabel = 'Prev N12'; }
        else if (q === 'Q3') { cumPrevVal = qe['PN9']; cumPrevLabel = 'Prev N9'; }
        else if (q === 'Q2') { cumPrevVal = qe['PN6']; cumPrevLabel = 'Prev N6'; }
        const cumPrevCell = cumPrevVal != null
            ? `${fmt(cumPrevVal)}<br><small style="color:#888">${cumPrevLabel}</small>`
            : (q === 'Q1' ? '<small style="color:#555">—</small>' : (cumPrevLabel ? `<small style="color:#555">${cumPrevLabel}</small>` : ''));

        // Previous full year EPS
        const prevFyEps = qe['PFY'];
        const prevFyCell = prevFyEps != null
            ? `${fmt(prevFyEps)}<br><small style="color:#888">Prev FY</small>`
            : '<small style="color:#555">Prev FY</small>';

        for (let fi = 0; fi < rowCount; fi++) {
            const formula = activeFormulas[fi];
            const isFirst = fi === 0;
            const isDefault = formula && formula.is_default;

            let computedEps, computedPe, exprLabel;
            const effectiveEps = (r.manual_fy_eps != null) ? r.manual_fy_eps : r.fy_eps;
            if (!formula || isDefault) {
                computedEps = r.fy_eps;
                computedPe = r.pe || (effectiveEps && effectiveEps > 0 && cmp > 0 ? +(cmp / effectiveEps).toFixed(2) : null);
                exprLabel = r.fy_eps_formula || '';
            } else {
                const expr = getFormulaExprForQuarter(formula, r.quarter);
                computedEps = evalFormulaExpr(expr, r.quarters_eps || {});
                computedPe = (computedEps && computedEps > 0 && cmp > 0) ? +(cmp / computedEps).toFixed(2) : null;
                exprLabel = expr || '';
            }

            const peVal = computedPe ? computedPe.toFixed(2) : '';
            const labelClass = isDefault ? 'pe-formula-label-default' : 'pe-formula-label-custom';
            const formulaTag = formula ? `<span class="pe-formula-label ${labelClass}">${formula.name}</span>` : '';
            const rowClass = isFirst ? '' : ' class="pe-formula-row"';

            const editBtnInner = `<button class="pe-edit-btn" onclick="peStartEdit('${sym}','${r.quarter}','${fy}')" title="Edit">${_SVG_PENCIL}</button>`;
            const deleteBtnInner = `<button class="pe-delete-btn" onclick="peDeleteRow('${sym}','${r.quarter}','${fy}')" title="Delete">${_SVG_TRASH}</button>`;
            const exchBadge = (r.exchange || 'NSE').toUpperCase() === 'BSE'
                ? '<span class="pe-exch-badge pe-exch-bse">BSE</span>'
                : '<span class="pe-exch-badge pe-exch-nse">NSE</span>';
            const valBadge = r.valuation === 'EXPENSIVE' ? '<span class="pe-val-badge pe-val-expensive">EXPENSIVE</span>'
                : r.valuation === 'CHEAP' ? '<span class="pe-val-badge pe-val-cheap">CHEAP</span>'
                : r.valuation ? `<span class="pe-val-badge pe-val-custom">${r.valuation}</span>`
                : '<span class="pe-val-badge pe-val-pending">PENDING</span>';
            const signalBadge = r.recommendation === 'BUY' ? '<span class="pe-signal-badge pe-signal-buy">BUY</span>'
                : r.recommendation === 'SELL' ? '<span class="pe-signal-badge pe-signal-sell">SELL</span>'
                : r.recommendation === 'HOLD' ? '<span class="pe-signal-badge pe-signal-hold">HOLD</span>'
                : '';
            const targetCell = r.target_price != null ? '₹' + fmt(r.target_price) : '';
            const manualEps = r.manual_fy_eps;
            const manualEpsFormula = r.manual_fy_eps_formula;
            let manualEpsCell = '';
            if (!isPending && manualEps != null) {
                let mfLabel = '';
                if (manualEpsFormula) {
                    try { const mf = JSON.parse(manualEpsFormula); mfLabel = mf[`${q.toLowerCase()}_expr`] || mf[`${q}_expr`] || ''; } catch(_) { mfLabel = ''; }
                }
                manualEpsCell = `<span style="color:#22c55e;font-weight:600">${fmt(manualEps)}</span>${mfLabel ? '<br><small style="color:#888">' + mfLabel + '</small>' : ''}`;
            }

            let remarkContent = valBadge;
            const actionBtns = isFailed ? (retryBtn + editBtnInner + deleteBtnInner) : (isPending ? deleteBtnInner : editBtnInner + deleteBtnInner);
            const editOrRetry = `<div class="pe-action-group">${actionBtns}</div>`;
            const commentText = r.comments ? `<span class="pe-comment-text" title="${(r.comments || '').replace(/"/g, '&quot;')}">${r.comments}</span>` : '';

            if (rowCount === 1) {
                html += `<tr data-pe-sym="${sym}" data-pe-q="${r.quarter}" data-pe-fy="${fy}" data-pe-basis="${r.eps_basis || 'C'}">
                    <td class="pvc-date">${updated}</td>
                    <td class="pvc-stock">${stockCell}${extBadge ? '<br>' + extBadge : ''}</td>
                    <td class="pvc-exch pe-col-exch">${exchBadge}</td>
                    <td class="pvc-quarter pe-col-quarter">${r.quarter || ''}</td>
                    <td class="pvc-year pe-col-year">${yearDisplay}</td>
                    <td class="pvc-qtreps pe-col-qtreps">${isPending ? '' : fmt(qtrEps) + basisBadge}</td>
                    <td class="pvc-epsqoq">${isPending ? '' : qoqCell}</td>
                    <td class="pvc-epsyoy">${isPending ? '' : yoyCell}</td>
                    <td class="pvc-cumeps">${isPending ? '' : cumCell}</td>
                    <td class="pvc-cumprevfy">${isPending ? '' : cumPrevCell}</td>
                    <td class="pvc-prevfyeps">${isPending ? '' : prevFyCell}</td>
                    <td class="pvc-fyeps pe-col-fyeps">${isPending ? '' : fmt(computedEps) + '<br><small style="color:#888">' + exprLabel + '</small>'}</td>
                    <td class="pvc-manualeps">${isPending ? '' : manualEpsCell}</td>
                    <td class="pvc-cmp pe-col-cmp">${isPending ? '' : (cmp ? '₹' + fmtCurrency(cmp) : '')}</td>
                    <td class="pvc-pe pe-col-pe ${isPending ? '' : peClassFor(computedPe)}" style="font-weight:600">${isPending ? '' : peVal}</td>
                    <td class="pvc-signal">${isPending ? '' : signalBadge}</td>
                    <td class="pvc-target">${isPending ? '' : targetCell}</td>
                    <td class="pvc-sector pe-col-sector"><small>${r.sector || ''}</small></td>
                    <td class="pvc-remark">${remarkContent}</td>
                    <td class="pvc-comments">${isPending ? `<small style="color:#ef4444">${r.extraction_error || ''}</small>` : commentText}</td>
                    <td class="pvc-file" style="text-align:center">${fileLink}</td>
                    <td class="pvc-edit" style="text-align:center">${editOrRetry}</td>
                </tr>`;
            } else if (isFirst) {
                html += `<tr data-pe-sym="${sym}" data-pe-q="${r.quarter}" data-pe-fy="${fy}" data-pe-basis="${r.eps_basis || 'C'}">
                    <td rowspan="${rowCount}" class="pvc-date">${updated}</td>
                    <td rowspan="${rowCount}" class="pvc-stock">${stockCell}${extBadge ? '<br>' + extBadge : ''}</td>
                    <td rowspan="${rowCount}" class="pvc-exch pe-col-exch">${exchBadge}</td>
                    <td rowspan="${rowCount}" class="pvc-quarter pe-col-quarter">${r.quarter || ''}</td>
                    <td rowspan="${rowCount}" class="pvc-year pe-col-year">${yearDisplay}</td>
                    <td rowspan="${rowCount}" class="pvc-qtreps pe-col-qtreps">${isPending ? '' : fmt(qtrEps) + basisBadge}</td>
                    <td rowspan="${rowCount}" class="pvc-epsqoq">${isPending ? '' : qoqCell}</td>
                    <td rowspan="${rowCount}" class="pvc-epsyoy">${isPending ? '' : yoyCell}</td>
                    <td rowspan="${rowCount}" class="pvc-cumeps">${isPending ? '' : cumCell}</td>
                    <td rowspan="${rowCount}" class="pvc-cumprevfy">${isPending ? '' : cumPrevCell}</td>
                    <td rowspan="${rowCount}" class="pvc-prevfyeps">${isPending ? '' : prevFyCell}</td>
                    <td class="pvc-fyeps">${isPending ? '' : formulaTag + ' ' + fmt(computedEps) + '<br><small style="color:#888">' + exprLabel + '</small>'}</td>
                    <td rowspan="${rowCount}" class="pvc-manualeps">${isPending ? '' : manualEpsCell}</td>
                    <td rowspan="${rowCount}" class="pvc-cmp pe-col-cmp">${isPending ? '' : (cmp ? '₹' + fmtCurrency(cmp) : '')}</td>
                    <td class="pvc-pe ${isPending ? '' : peClassFor(computedPe)}" style="font-weight:600">${isPending ? '' : peVal}</td>
                    <td rowspan="${rowCount}" class="pvc-signal">${isPending ? '' : signalBadge}</td>
                    <td rowspan="${rowCount}" class="pvc-target">${isPending ? '' : targetCell}</td>
                    <td rowspan="${rowCount}" class="pvc-sector pe-col-sector"><small>${r.sector || ''}</small></td>
                    <td rowspan="${rowCount}" class="pvc-remark">${remarkContent}</td>
                    <td rowspan="${rowCount}" class="pvc-comments">${isPending ? `<small style="color:#ef4444">${r.extraction_error || ''}</small>` : commentText}</td>
                    <td rowspan="${rowCount}" class="pvc-file" style="text-align:center">${fileLink}</td>
                    <td rowspan="${rowCount}" class="pvc-edit" style="text-align:center">${editOrRetry}</td>
                </tr>`;
            } else {
                html += `<tr${rowClass}>
                    <td class="pvc-fyeps">${formulaTag} ${fmt(computedEps)}<br><small style="color:#888">${exprLabel}</small></td>
                    <td class="pvc-pe ${peClassFor(computedPe)}" style="font-weight:600">${peVal}</td>
                </tr>`;
            }
        }
    }
    tbody.innerHTML = html;
    _syncPETopScroll();
}

async function peRetryExtraction(symbol, btnEl) {
    if (!symbol) return;
    const origHtml = btnEl.innerHTML;
    btnEl.disabled = true;
    btnEl.innerHTML = '<span class="pe-ext-spinner"></span> Retrying...';
    try {
        const resp = await fetch(`/api/retry_extraction/${encodeURIComponent(symbol)}`, { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
            const item = peAnalysisData.find(r => r.stock_symbol === symbol && r.extraction_status === 'failed');
            if (item) {
                item.extraction_status = 'queued';
                item.extraction_error = null;
            }
            renderPEAnalysis();
        } else {
            btnEl.innerHTML = origHtml;
            btnEl.disabled = false;
            alert(data.detail || 'Retry failed');
        }
    } catch (e) {
        btnEl.innerHTML = origHtml;
        btnEl.disabled = false;
        alert('Retry failed: ' + e.message);
    }
}

function handleExtractionStatusUpdate(data) {
    const sym = data.stock_symbol;
    const status = data.status;
    if (!sym) return;

    let updated = false;
    (peAnalysisData || []).forEach(r => {
        if (r.stock_symbol === sym && r.extraction_status !== 'completed') {
            r.extraction_status = status;
            if (status === 'completed' || status === 'failed') {
                r.extraction_error = data.error || null;
            }
            updated = true;
        }
    });

    if (updated) {
        renderPEAnalysis();
    }

    if (status === 'completed') {
        loadPEAnalysis();
    }
}

function renderPEPagination(totalPages, totalItems, perPage) {
    document.querySelectorAll('.pe-pagination').forEach(wrap => {
        if (perPage <= 0 || totalPages <= 1) {
            wrap.style.display = 'none';
            return;
        }
        wrap.style.display = 'flex';

        wrap.querySelector('.pe-page-first').disabled = peCurrentPage <= 1;
        wrap.querySelector('.pe-page-prev').disabled = peCurrentPage <= 1;
        wrap.querySelector('.pe-page-next').disabled = peCurrentPage >= totalPages;
        wrap.querySelector('.pe-page-last').disabled = peCurrentPage >= totalPages;

        const numContainer = wrap.querySelector('.pe-page-numbers');
        const pages = _buildPageList(peCurrentPage, totalPages, 7);
        numContainer.innerHTML = pages.map(p => {
            if (p === '...') return '<span class="pe-page-ellipsis">...</span>';
            const cls = p === peCurrentPage ? 'pe-page-num active' : 'pe-page-num';
            return `<button class="${cls}" data-page="${p}">${p}</button>`;
        }).join('');

        const input = wrap.querySelector('.pe-page-input');
        input.max = totalPages;
        input.placeholder = `${peCurrentPage}/${totalPages}`;
        input.value = '';

        wrap.querySelector('.pe-page-total').textContent =
            `Page ${peCurrentPage} of ${totalPages}`;
    });
}

function _peGoToPage(page) {
    if (peServerLimit <= 0) return;
    peCurrentPage = Math.max(1, Math.min(page, peTotalPages));
    loadPEAnalysis();
    document.getElementById('peTableContainer')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

(function initPEPaginationControls() {
    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('.pe-pagination').forEach(wrap => {
            wrap.querySelector('.pe-page-first')?.addEventListener('click', () => _peGoToPage(1));
            wrap.querySelector('.pe-page-prev')?.addEventListener('click', () => _peGoToPage(peCurrentPage - 1));
            wrap.querySelector('.pe-page-next')?.addEventListener('click', () => _peGoToPage(peCurrentPage + 1));
            wrap.querySelector('.pe-page-last')?.addEventListener('click', () => {
                _peGoToPage(peTotalPages);
            });
            wrap.querySelector('.pe-page-numbers')?.addEventListener('click', e => {
                const btn = e.target.closest('[data-page]');
                if (btn) _peGoToPage(parseInt(btn.dataset.page, 10));
            });
            const goBtn = wrap.querySelector('.pe-go-btn');
            const input = wrap.querySelector('.pe-page-input');
            if (goBtn && input) {
                goBtn.addEventListener('click', () => {
                    const v = parseInt(input.value, 10);
                    if (v >= 1) _peGoToPage(v);
                });
                input.addEventListener('keydown', e => {
                    if (e.key === 'Enter') {
                        const v = parseInt(input.value, 10);
                        if (v >= 1) _peGoToPage(v);
                    }
                });
            }
        });
    });
})();

function _syncPETopScroll() {
    const topScroll = document.getElementById('peTopScroll');
    const container = document.getElementById('peTableContainer');
    const table = document.getElementById('peAnalysisTable');
    if (!topScroll || !container || !table) return;
    topScroll.firstElementChild.style.width = table.scrollWidth + 'px';
    let syncing = false;
    topScroll.onscroll = () => { if (!syncing) { syncing = true; container.scrollLeft = topScroll.scrollLeft; syncing = false; } };
    container.onscroll = () => { if (!syncing) { syncing = true; topScroll.scrollLeft = container.scrollLeft; syncing = false; } };
}

// PE Inline Edit
let _peSectorsList = null;
let _peSubSectorsMap = null;
let _peSectorFormulasCache = null;

function _peCheckDirty() {
    const btn = document.getElementById('pePanelSaveBtn');
    if (!btn) return;
    const body = document.getElementById('peDrawerBody');
    if (!body) return;
    let dirty = false;
    body.querySelectorAll('.pe-drawer-input').forEach(el => {
        const orig = el.getAttribute('data-orig');
        if (orig !== null && el.value !== orig) dirty = true;
    });
    btn.disabled = !dirty;
    btn.classList.toggle('pe-save-disabled', !dirty);
}

async function _loadPeSectors() {
    if (_peSectorsList) return _peSectorsList;
    try {
        const resp = await fetch('/api/pe_sectors', { headers: getAuthHeaders() });
        const data = await resp.json();
        if (data.success) {
            _peSectorsList = data.sectors || [];
            _peSubSectorsMap = data.sub_sectors || {};
        }
    } catch (e) { _peSectorsList = []; _peSubSectorsMap = {}; }
    return _peSectorsList || [];
}

async function _loadSectorFormulas() {
    if (_peSectorFormulasCache) return _peSectorFormulasCache;
    try {
        const resp = await fetch('/api/sector_formulas', { headers: getAuthHeaders() });
        const data = await resp.json();
        if (data.success) _peSectorFormulasCache = data.sector_formulas || [];
    } catch (e) { _peSectorFormulasCache = []; }
    return _peSectorFormulasCache || [];
}

function _getSectorFormulaForEdit(sector, subSector) {
    if (!_peSectorFormulasCache || !sector) return null;
    let match = _peSectorFormulasCache.find(sf => sf.sector === sector && sf.sub_sector === subSector);
    if (!match && subSector) match = _peSectorFormulasCache.find(sf => sf.sector === sector && !sf.sub_sector);
    return match ? match.formulas : null;
}

function _yearOptions(selected) {
    const cur = new Date().getFullYear();
    let opts = '';
    for (let y = cur + 2; y >= 2018; y--) opts += `<option value="${y}"${String(y) === String(selected) ? ' selected' : ''}>FY${String(y).slice(-2)}</option>`;
    return opts;
}

function _peGetCustomRemarks() {
    try {
        return JSON.parse(localStorage.getItem('peCustomRemarks') || '[]');
    } catch (e) { return []; }
}

function _peSaveCustomRemarks(tags) {
    localStorage.setItem('peCustomRemarks', JSON.stringify(tags));
}

function _peRemarkDropdownHtml(currentVal) {
    const builtIn = ['', 'CHEAP', 'EXPENSIVE'];
    const custom = _peGetCustomRemarks();
    if (currentVal && !builtIn.includes(currentVal) && !custom.includes(currentVal)) {
        custom.push(currentVal);
        _peSaveCustomRemarks(custom);
    }
    const allOpts = [...builtIn, ...custom];
    const display = currentVal || '—';
    let listHtml = allOpts.map(v => {
        const label = v || '—';
        const isCustom = v && !builtIn.includes(v);
        const sel = v === currentVal ? ' pe-rdd-selected' : '';
        const del = isCustom ? `<span class="pe-rdd-del" data-del="${v}" title="Delete">✕</span>` : '';
        return `<div class="pe-rdd-opt${sel}" data-val="${v}">${label}${del}</div>`;
    }).join('');
    listHtml += `<div class="pe-rdd-opt pe-rdd-add" data-val="__custom__">+ Add custom…</div>`;
    return `<div class="pe-remark-dd">
        <input type="hidden" class="pe-drawer-input" data-field="valuation" data-orig="${currentVal || ''}" value="${currentVal || ''}">
        <div class="pe-rdd-trigger">${display}</div>
        <div class="pe-rdd-list">${listHtml}</div>
    </div>`;
}

function _peInitRemarkDropdown(container) {
    const dd = container.querySelector('.pe-remark-dd');
    if (!dd) return;
    const trigger = dd.querySelector('.pe-rdd-trigger');
    const list = dd.querySelector('.pe-rdd-list');
    const hidden = dd.querySelector('input[data-field="valuation"]');

    trigger.addEventListener('click', () => {
        const isOpen = list.classList.contains('pe-rdd-open');
        document.querySelectorAll('.pe-rdd-list.pe-rdd-open').forEach(l => l.classList.remove('pe-rdd-open'));
        if (!isOpen) list.classList.add('pe-rdd-open');
    });

    list.addEventListener('click', (e) => {
        const delBtn = e.target.closest('.pe-rdd-del');
        if (delBtn) {
            e.stopPropagation();
            const tag = delBtn.dataset.del;
            const custom = _peGetCustomRemarks().filter(t => t !== tag);
            _peSaveCustomRemarks(custom);
            delBtn.closest('.pe-rdd-opt').remove();
            if (hidden.value === tag) {
                hidden.value = '';
                trigger.textContent = '—';
                list.querySelector('.pe-rdd-selected')?.classList.remove('pe-rdd-selected');
                list.querySelector('[data-val=""]')?.classList.add('pe-rdd-selected');
            }
            _peCheckDirty();
            return;
        }
        const opt = e.target.closest('.pe-rdd-opt');
        if (!opt) return;
        const val = opt.dataset.val;
        if (val === '__custom__') {
            list.classList.remove('pe-rdd-open');
            _peShowCustomRemarkInput(dd, trigger, list, hidden);
            return;
        }
        hidden.value = val;
        trigger.textContent = val || '—';
        list.querySelectorAll('.pe-rdd-selected').forEach(el => el.classList.remove('pe-rdd-selected'));
        opt.classList.add('pe-rdd-selected');
        list.classList.remove('pe-rdd-open');
        _peCheckDirty();
    });

    document.addEventListener('click', (e) => {
        if (!dd.contains(e.target)) list.classList.remove('pe-rdd-open');
    });
}

function _peShowCustomRemarkInput(dd, trigger, list, hidden) {
    const existing = dd.querySelector('.pe-custom-remark-input');
    if (existing) { existing.querySelector('input').focus(); return; }

    const wrap = document.createElement('div');
    wrap.className = 'pe-custom-remark-input';
    wrap.innerHTML = `
        <input type="text" class="pe-drawer-input" placeholder="e.g. UNDERVALUED" style="width:100%;margin-top:6px;font-size:0.8rem;" autofocus>
        <div style="display:flex;gap:4px;margin-top:4px;">
            <button type="button" class="pe-custom-remark-ok" style="flex:1;">Add</button>
            <button type="button" class="pe-custom-remark-cancel" style="flex:0 0 auto;">Cancel</button>
        </div>
    `;
    dd.appendChild(wrap);
    const inp = wrap.querySelector('input');
    setTimeout(() => inp.focus(), 0);

    const confirmAdd = () => {
        const val = inp.value.trim().toUpperCase();
        if (!val) { cancelAdd(); return; }
        const custom = _peGetCustomRemarks();
        if (!custom.includes(val)) { custom.push(val); _peSaveCustomRemarks(custom); }
        const newOpt = document.createElement('div');
        newOpt.className = 'pe-rdd-opt pe-rdd-selected';
        newOpt.dataset.val = val;
        newOpt.innerHTML = `${val}<span class="pe-rdd-del" data-del="${val}" title="Delete">✕</span>`;
        list.querySelector('.pe-rdd-add').before(newOpt);
        list.querySelectorAll('.pe-rdd-selected').forEach(el => { if (el !== newOpt) el.classList.remove('pe-rdd-selected'); });
        hidden.value = val;
        trigger.textContent = val;
        wrap.remove();
        _peCheckDirty();
    };
    const cancelAdd = () => { wrap.remove(); };

    wrap.querySelector('.pe-custom-remark-ok').onclick = confirmAdd;
    wrap.querySelector('.pe-custom-remark-cancel').onclick = cancelAdd;
    inp.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); confirmAdd(); }
        if (e.key === 'Escape') { cancelAdd(); }
    });
}

function peStartEdit(sym, quarter, fy) {
    peCancelEdit();
    const row = document.querySelector(`tr[data-pe-sym="${sym}"][data-pe-q="${quarter}"][data-pe-fy="${fy}"]`);
    if (row) row.classList.add('pe-editing');

    const r = peAnalysisData.find(d => d.stock_symbol === sym && d.quarter === quarter && d.financial_year === fy);
    if (!r) return;

    const basis = r.eps_basis || 'C';
    const curExch = (r.exchange || 'NSE').toUpperCase();
    const yearVal = _fyEndingYear(fy) || fy;

    const drawer = document.getElementById('peEditDrawer');
    const backdrop = document.getElementById('peEditDrawerBackdrop');
    const titleEl = document.getElementById('peDrawerTitle');
    const body = document.getElementById('peDrawerBody');
    const saveBtn = document.getElementById('pePanelSaveBtn');

    titleEl.innerHTML = `${_SVG_PENCIL} ${r.company_name || sym}`;

    const exchOpts = ['NSE','BSE'].map(e => `<option value="${e}"${e === curExch ? ' selected' : ''}>${e}</option>`).join('');
    const qtrOpts = ['Q1','Q2','Q3','Q4','FY'].map(q => `<option value="${q}"${q === quarter ? ' selected' : ''}>${q}</option>`).join('');

    const fyEpsVal = r.fy_eps != null ? r.fy_eps : '';
    const peVal = r.pe != null ? r.pe : '';

    const manualVal = r.manual_fy_eps != null ? r.manual_fy_eps : '';
    let existingFormula = {};
    if (r.manual_fy_eps_formula) {
        try { existingFormula = JSON.parse(r.manual_fy_eps_formula); } catch(_) {}
    }

    body.innerHTML = `
        <div class="pe-drawer-info">
            <strong>${sym}</strong> &mdash; ${quarter} ${fy}<br>
            <span style="font-size:0.8rem;color:#6b7280;">${curExch} &bull; Qtr EPS: ${r.qtr_eps != null ? r.qtr_eps : '—'}</span>
        </div>
        <div class="pe-drawer-field">
            <label>CMP (₹)</label>
            <input type="number" step="0.01" class="pe-drawer-input" data-field="cmp" value="${r.cmp != null ? r.cmp : ''}" data-orig="${r.cmp != null ? r.cmp : ''}" placeholder="—">
        </div>
        <div class="pe-drawer-field">
            <label>FY EPS (Est.) <small style="color:#888">auto-calculated</small></label>
            <input type="number" step="0.01" class="pe-drawer-input" data-field="fy_eps" value="${fyEpsVal}" data-orig="${fyEpsVal}" placeholder="—">
        </div>
        <div class="pe-drawer-divider" style="border-top:1px solid rgba(34,197,94,0.3);margin:12px 0 8px;"></div>
        <div class="pe-drawer-field">
            <label style="color:#f59e0b;font-weight:700;">Manual FY EPS (Estimated)</label>
            <input type="number" step="0.01" class="pe-drawer-input" data-field="manual_fy_eps" value="${manualVal}" data-orig="${manualVal}" placeholder="Override auto EPS">
        </div>
        <div class="pe-drawer-field">
            <label style="font-size:0.75rem;color:#9ca3af;">Formula per Quarter <small>(used to derive manual EPS)</small></label>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
                <div><label style="font-size:0.7rem;color:#6b7280;">Q1</label><input type="text" class="pe-drawer-input pe-formula-input" data-field="formula_q1" value="${existingFormula.q1_expr || ''}" data-orig="${existingFormula.q1_expr || ''}" placeholder="e.g. Q1*4"></div>
                <div><label style="font-size:0.7rem;color:#6b7280;">Q2</label><input type="text" class="pe-drawer-input pe-formula-input" data-field="formula_q2" value="${existingFormula.q2_expr || ''}" data-orig="${existingFormula.q2_expr || ''}" placeholder="e.g. (Q1+Q2)*2"></div>
                <div><label style="font-size:0.7rem;color:#6b7280;">Q3</label><input type="text" class="pe-drawer-input pe-formula-input" data-field="formula_q3" value="${existingFormula.q3_expr || ''}" data-orig="${existingFormula.q3_expr || ''}" placeholder="e.g. (Q1+Q2+Q3)*4/3"></div>
                <div><label style="font-size:0.7rem;color:#6b7280;">Q4</label><input type="text" class="pe-drawer-input pe-formula-input" data-field="formula_q4" value="${existingFormula.q4_expr || ''}" data-orig="${existingFormula.q4_expr || ''}" placeholder="e.g. FY"></div>
            </div>
        </div>
        <div class="pe-drawer-divider" style="border-top:1px solid rgba(255,255,255,0.08);margin:8px 0;"></div>
        <div class="pe-drawer-field">
            <label>PE Value</label>
            <input type="number" step="0.01" class="pe-drawer-input" data-field="pe" value="${peVal}" data-orig="${peVal}" placeholder="—" readonly style="background:#f3f4f6;color:#6b7280;">
        </div>
        <div class="pe-drawer-field" style="position:relative;">
            <label>Sector</label>
            <input type="text" class="pe-drawer-input pe-sector-input" data-field="sector" value="${r.sector || ''}" data-orig="${r.sector || ''}" placeholder="Select or type sector" autocomplete="off">
            <div class="pe-sector-dropdown" style="display:none;"></div>
        </div>
        <div class="pe-drawer-field">
            <label>Sub-Sector</label>
            <input type="text" class="pe-drawer-input" data-field="sub_sector" value="${r.sub_sector || ''}" data-orig="${r.sub_sector || ''}" placeholder="e.g. NBFC, Insurance" list="peSubSectorList">
            <datalist id="peSubSectorList"></datalist>
        </div>
        <div class="pe-drawer-field">
            <label>Signal</label>
            <select class="pe-drawer-input" data-field="recommendation" data-orig="${r.recommendation || ''}">
                <option value=""${!r.recommendation ? ' selected' : ''}>—</option>
                <option value="BUY"${r.recommendation === 'BUY' ? ' selected' : ''}>BUY</option>
                <option value="SELL"${r.recommendation === 'SELL' ? ' selected' : ''}>SELL</option>
                <option value="HOLD"${r.recommendation === 'HOLD' ? ' selected' : ''}>HOLD</option>
            </select>
        </div>
        <div class="pe-drawer-field">
            <label>Target Price (₹)</label>
            <input type="number" step="0.01" class="pe-drawer-input" data-field="target_price" value="${r.target_price != null ? r.target_price : ''}" data-orig="${r.target_price != null ? r.target_price : ''}" placeholder="—">
        </div>
        <div class="pe-drawer-field">
            <label>Remark</label>
            ${_peRemarkDropdownHtml(r.valuation || '')}
        </div>
        <div class="pe-drawer-field">
            <label>Comments</label>
            <textarea class="pe-drawer-input" data-field="comments" data-orig="${(r.comments || '').replace(/"/g, '&quot;')}" rows="3" placeholder="Add a comment…">${r.comments || ''}</textarea>
        </div>
    `;

    saveBtn.onclick = () => peSaveEdit(sym, quarter, fy, basis);
    saveBtn.disabled = true;
    saveBtn.classList.add('pe-save-disabled');

    _peInitRemarkDropdown(body);

    backdrop.style.display = 'block';
    backdrop.onclick = () => peCancelEdit();
    requestAnimationFrame(() => drawer.classList.add('open'));

    const _recalcPE = () => {
        const cmpEl = body.querySelector('[data-field="cmp"]');
        const manualEl = body.querySelector('[data-field="manual_fy_eps"]');
        const epsEl = body.querySelector('[data-field="fy_eps"]');
        const peEl = body.querySelector('[data-field="pe"]');
        if (!cmpEl || !peEl) return;
        const c = parseFloat(cmpEl.value);
        const mEps = manualEl ? parseFloat(manualEl.value) : NaN;
        const aEps = epsEl ? parseFloat(epsEl.value) : NaN;
        const e = !isNaN(mEps) && mEps > 0 ? mEps : aEps;
        peEl.value = (c > 0 && e > 0) ? (c / e).toFixed(2) : '';
    };
    body.querySelector('[data-field="cmp"]')?.addEventListener('input', () => { _recalcPE(); _peCheckDirty(); });
    body.querySelector('[data-field="fy_eps"]')?.addEventListener('input', () => { _recalcPE(); _peCheckDirty(); });
    body.querySelector('[data-field="manual_fy_eps"]')?.addEventListener('input', () => { _recalcPE(); _peCheckDirty(); });

    // Load sectors + sub_sectors + sector formulas
    Promise.all([_loadPeSectors(), _loadSectorFormulas()]).then(([sectors]) => {
        const sectorInput = body.querySelector('[data-field="sector"]');
        const dropdown = body.querySelector('.pe-sector-dropdown');
        if (sectorInput && dropdown) {
            let allSectors = sectors || [];
            const renderDD = (filter) => {
                const q = (filter || '').toLowerCase();
                const filtered = q ? allSectors.filter(s => s.toLowerCase().includes(q)) : allSectors;
                dropdown.innerHTML = filtered.map(s =>
                    `<div class="pe-sector-opt${s === sectorInput.value ? ' active' : ''}">${s}</div>`
                ).join('') || '<div class="pe-sector-opt" style="color:#94a3b8;pointer-events:none;">No match</div>';
                dropdown.style.display = filtered.length || q ? 'block' : 'none';
            };
            sectorInput.addEventListener('focus', () => renderDD(sectorInput.value));
            sectorInput.addEventListener('input', () => {
                renderDD(sectorInput.value);
                _peCheckDirty();
                _peUpdateSubSectorList(body, sectorInput.value);
                _pePrefillSectorFormulas(body, sectorInput.value, body.querySelector('[data-field="sub_sector"]')?.value);
            });
            dropdown.addEventListener('click', (e) => {
                const opt = e.target.closest('.pe-sector-opt');
                if (!opt || opt.style.pointerEvents === 'none') return;
                sectorInput.value = opt.textContent;
                dropdown.style.display = 'none';
                sectorInput.dispatchEvent(new Event('input'));
            });
            document.addEventListener('click', (e) => {
                if (!sectorInput.contains(e.target) && !dropdown.contains(e.target)) dropdown.style.display = 'none';
            });
        }
        _peUpdateSubSectorList(body, r.sector || '');
        _pePrefillSectorFormulas(body, r.sector || '', r.sub_sector || '');
    });

    body.querySelector('[data-field="sub_sector"]')?.addEventListener('input', () => {
        _peCheckDirty();
        const sec = body.querySelector('[data-field="sector"]')?.value || '';
        const sub = body.querySelector('[data-field="sub_sector"]')?.value || '';
        _pePrefillSectorFormulas(body, sec, sub);
    });

    body.querySelectorAll('.pe-drawer-input').forEach(el => {
        el.addEventListener(el.tagName === 'SELECT' ? 'change' : 'input', _peCheckDirty);
    });

    if (drawer && typeof refreshIcons === 'function') refreshIcons(drawer);
}

function _peUpdateSubSectorList(body, sector) {
    const dl = body.querySelector('#peSubSectorList');
    if (!dl || !_peSubSectorsMap) return;
    const subs = _peSubSectorsMap[sector] || [];
    dl.innerHTML = subs.map(s => `<option value="${s}">`).join('');
}

function _pePrefillSectorFormulas(body, sector, subSector) {
    if (!sector) return;
    const formulas = _getSectorFormulaForEdit(sector, subSector);
    if (!formulas) return;
    ['q1','q2','q3','q4'].forEach(qk => {
        const inp = body.querySelector(`[data-field="formula_${qk}"]`);
        if (inp && !inp.value) {
            const key = `${qk.toUpperCase()}`;
            inp.value = formulas[key] || '';
        }
    });
}

async function peSaveEdit(sym, oldQuarter, oldFy, basis) {
    const panel = document.getElementById('peDrawerBody');
    if (!panel) return;

    const getVal = (field) => {
        const el = panel.querySelector(`[data-field="${field}"]`);
        return el ? el.value : null;
    };

    const newQuarter = getVal('quarter');
    const newYear = getVal('year');
    const qtrEps = getVal('qtr_eps');
    const fyEps = getVal('fy_eps');
    const cmpVal = getVal('cmp');
    const sector = getVal('sector');
    const exchange = getVal('exchange');

    const body = {
        old_quarter: oldQuarter,
        old_financial_year: oldFy,
        eps_basis: basis
    };
    if (newQuarter && newQuarter !== oldQuarter) body.quarter = newQuarter;
    if (newYear) {
        const newFy = `FY${parseInt(newYear) - 1}-${newYear.slice(-2)}`;
        if (newFy !== oldFy) body.financial_year = newFy;
    }
    if (qtrEps !== '' && qtrEps !== null) body.qtr_eps = parseFloat(qtrEps);
    if (fyEps !== '' && fyEps !== null) body.fy_eps = parseFloat(fyEps);
    if (cmpVal !== '' && cmpVal !== null) body.cmp = parseFloat(cmpVal);
    if (sector !== null) body.sector = sector;
    if (exchange !== null) body.exchange = exchange;
    const subSector = getVal('sub_sector');
    if (subSector !== null) body.sub_sector = subSector;
    const manualEps = getVal('manual_fy_eps');
    if (manualEps !== '' && manualEps !== null) body.manual_fy_eps = parseFloat(manualEps);

    const fq1 = getVal('formula_q1'), fq2 = getVal('formula_q2'), fq3 = getVal('formula_q3'), fq4 = getVal('formula_q4');
    const hasFormula = !!(fq1 || fq2 || fq3 || fq4);
    if (hasFormula) {
        body.manual_fy_eps_formula = JSON.stringify({ q1_expr: fq1 || '', q2_expr: fq2 || '', q3_expr: fq3 || '', q4_expr: fq4 || '' });
    }

    // Ask user to save as sector default if formula was entered
    if (hasFormula && sector) {
        const subLabel = subSector ? ` > ${subSector}` : '';
        const saveAsDefault = confirm(`Save this formula as default for sector "${sector}${subLabel}"?\n\nQ1: ${fq1 || '—'}\nQ2: ${fq2 || '—'}\nQ3: ${fq3 || '—'}\nQ4: ${fq4 || '—'}\n\nClick OK to apply as sector default, Cancel to save for this stock only.`);
        body.save_as_sector_default = saveAsDefault;
        if (saveAsDefault) _peSectorFormulasCache = null;
    }

    const valuation = getVal('valuation');
    if (valuation !== null) body.valuation = valuation;
    const comments = getVal('comments');
    if (comments !== null) body.comments = comments;
    const recommendation = getVal('recommendation');
    if (recommendation !== null) body.recommendation = recommendation;
    const targetPrice = getVal('target_price');
    if (targetPrice !== '' && targetPrice !== null) body.target_price = parseFloat(targetPrice);

    try {
        const resp = await fetch(`/api/pe_analysis/${encodeURIComponent(sym)}`, {
            method: 'PUT',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await resp.json();
        if (data.success) {
            peCancelEdit();
            loadPEAnalysis();
            showNotificationToast('Row saved', 'success');
        } else {
            showNotificationToast(data.detail || 'Save failed', 'error');
        }
    } catch (e) {
        console.error('PE save error:', e);
        showNotificationToast('Save failed', 'error');
    }
}

function peCancelEdit() {
    const drawer = document.getElementById('peEditDrawer');
    const backdrop = document.getElementById('peEditDrawerBackdrop');
    if (drawer) drawer.classList.remove('open');
    if (backdrop) backdrop.style.display = 'none';
    document.querySelectorAll('.pe-editing').forEach(el => el.classList.remove('pe-editing'));
}

async function peDeleteRow(sym, quarter, fy) {
    if (!confirm(`Delete ${sym} ${quarter} ${fy} from PE Analysis? This cannot be undone.`)) return;
    try {
        const resp = await fetch(`/api/pe_analysis/${encodeURIComponent(sym)}?quarter=${encodeURIComponent(quarter)}&financial_year=${encodeURIComponent(fy)}`, {
            method: 'DELETE',
            headers: getAuthHeaders()
        });
        const data = await resp.json();
        if (data.success) {
            loadPEAnalysis();
            showNotificationToast(`Deleted ${sym} ${quarter}`, 'success');
        } else {
            showNotificationToast(data.detail || 'Delete failed', 'error');
        }
    } catch (e) {
        console.error('PE delete error:', e);
        showNotificationToast('Delete failed', 'error');
    }
}

function exportPEAnalysisToExcel() {
    const filtered = peAnalysisData;
    if (!filtered.length) return;

    const activeFormulas = peFormulas.filter(f => peActiveFormulaIds.includes(f.id));
    if (activeFormulas.length === 0 && peFormulas.length > 0) {
        const def = peFormulas.find(f => f.is_default);
        if (def) activeFormulas.push(def);
    }
    const rowCount = Math.max(activeFormulas.length, 1);

    const rows = [];
    const header = ['Date', 'Stock', 'Company', 'Quarter', 'Year', 'Qtr EPS', 'EPS Q/Q', 'EPS Y/Y', 'Cum EPS', 'Cum Prev FY', 'Prev FY EPS', 'Formula', 'FY EPS (Est.)', 'FY EPS Formula', 'CMP', 'PE', 'Sector', 'Remark', 'Comments'];
    rows.push(header);

    for (const r of filtered) {
        const fy = r.financial_year || '';
        const ym = _fyEndingYear(fy);
        const yearDisplay = ym ? 'FY' + ym.slice(-2) : fy;
        const qe = r.quarters_eps || {};
        const q = (r.quarter || '').toUpperCase();
        let cumEpsVal = null;
        if (q === 'Q4' || q === 'FY') cumEpsVal = qe['N12'] || qe['FY'];
        else if (q === 'Q3') cumEpsVal = qe['N9'];
        else if (q === 'Q2') cumEpsVal = qe['N6'];
        const qoqMap = { Q2: 'Q1', Q3: 'Q2', Q4: 'Q3', Q1: 'PQ4' };
        const epsQoQVal = qoqMap[q] ? qe[qoqMap[q]] : null;
        const epsYoYVal = q ? qe[`P${q}`] : null;
        let cumPrevFyVal = null;
        if (q === 'Q4' || q === 'FY') cumPrevFyVal = qe['PFY'];
        else if (q === 'Q3') cumPrevFyVal = qe['PN9'];
        else if (q === 'Q2') cumPrevFyVal = qe['PN6'];
        const prevFyEpsVal = qe['PFY'];
        const exportDateSource = r.announcement_date || r.updated_at;
        const updated = exportDateSource ? new Date(exportDateSource).toLocaleString('en-IN', { day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit', hour12:true }) : '';

        for (let fi = 0; fi < rowCount; fi++) {
            const formula = activeFormulas[fi];
            const isDefault = formula && formula.is_default;
            let computedEps, computedPe, exprLabel, formulaName;
            if (!formula || isDefault) {
                computedEps = r.fy_eps;
                computedPe = r.pe || (r.fy_eps && r.fy_eps > 0 && r.cmp > 0 ? +(r.cmp / r.fy_eps).toFixed(2) : null);
                exprLabel = r.fy_eps_formula || '';
                formulaName = formula ? formula.name : 'Default';
            } else {
                const expr = getFormulaExprForQuarter(formula, r.quarter);
                computedEps = evalFormulaExpr(expr, r.quarters_eps || {});
                computedPe = (computedEps && computedEps > 0 && r.cmp > 0) ? +(r.cmp / computedEps).toFixed(2) : null;
                exprLabel = expr || '';
                formulaName = formula.name;
            }
            rows.push([
                updated,
                r.stock_symbol || '',
                r.company_name || '',
                r.quarter || '',
                yearDisplay,
                r.qtr_eps ?? '',
                epsQoQVal ?? '',
                epsYoYVal ?? '',
                cumEpsVal ?? '',
                cumPrevFyVal ?? '',
                prevFyEpsVal ?? '',
                formulaName,
                computedEps ?? '',
                exprLabel,
                r.cmp ?? '',
                computedPe ?? '',
                r.sector || '',
                r.valuation || '',
                r.comments || '',
            ]);
        }
    }

    let csv = '\uFEFF';
    for (const row of rows) {
        csv += row.map(v => {
            const s = String(v ?? '');
            return s.includes(',') || s.includes('"') || s.includes('\n') ? '"' + s.replace(/"/g, '""') + '"' : s;
        }).join(',') + '\r\n';
    }

    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `PE_Analysis_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
}

// ============================================================================
// ANALYTICS REPORT
// ============================================================================
let _arData = null;
let _arSortKey = 'count';
let _arSortAsc = false;

async function loadAnalyticsReport() {
    const loading = document.getElementById('arLoading');
    const empty = document.getElementById('arEmpty');
    const content = document.getElementById('arContent');
    loading.style.display = 'flex';
    empty.style.display = 'none';
    content.style.display = 'none';
    try {
        const resp = await fetch('/api/pe_analysis/report_summary', { headers: getAuthHeaders() });
        const data = await resp.json();
        if (!data.success || !data.summary || data.summary.total_reviewed === 0) {
            loading.style.display = 'none';
            empty.style.display = 'flex';
            return;
        }
        _arData = data.summary;
        renderAnalyticsReport();
        loading.style.display = 'none';
        content.style.display = 'block';
    } catch (e) {
        console.error('Analytics report error:', e);
        loading.style.display = 'none';
        empty.style.display = 'flex';
    }
}

function renderAnalyticsReport() {
    const d = _arData;
    const badge = document.getElementById('arTotalBadge');
    badge.textContent = `${d.total_reviewed} stocks`;
    badge.style.display = 'inline-block';
    _renderARCards(d);
    _renderARPEChart(d.pe_distribution);
    _renderARValChart(d.valuation_counts);
    _renderARSectorTable(d.sector_summary);
    _renderARTop10(d.top10_cheapest, 'arCheapBody');
    _renderARTop10(d.top10_expensive, 'arExpBody');
}

function _renderARCards(d) {
    const rc = d.recommendation_counts || {};
    const cards = [
        { label: 'Total Reviewed', value: d.total_reviewed, icon: 'check-circle', cls: 'ar-card-total' },
        { label: 'BUY Signals', value: rc.BUY || 0, icon: 'trending-up', cls: 'ar-card-buy' },
        { label: 'SELL Signals', value: rc.SELL || 0, icon: 'trending-down', cls: 'ar-card-sell' },
        { label: 'HOLD Signals', value: rc.HOLD || 0, icon: 'pause', cls: 'ar-card-hold' },
        { label: 'Avg PE', value: d.avg_pe != null ? d.avg_pe.toFixed(1) : '—', icon: 'calculator', cls: 'ar-card-pe', sub: d.median_pe != null ? `Median: ${d.median_pe.toFixed(1)}` : '' },
    ];
    document.getElementById('arCards').innerHTML = cards.map(c =>
        `<div class="ar-card ${c.cls}"><div class="ar-card-icon"><i data-lucide="${c.icon}"></i></div><div class="ar-card-body"><div class="ar-card-value">${c.value}</div><div class="ar-card-label">${c.label}</div>${c.sub ? `<div class="ar-card-sub">${c.sub}</div>` : ''}</div></div>`
    ).join('');
    refreshIcons(document.getElementById('arCards'));
}

function _renderARPEChart(dist) {
    const max = Math.max(...dist.map(b => b.count), 1);
    document.getElementById('arPEChart').innerHTML = dist.map(b => {
        const pct = Math.round(b.count / max * 100);
        return `<div class="ar-bar-item"><div class="ar-bar-label">${b.range}</div><div class="ar-bar-track"><div class="ar-bar-fill" style="width:${pct}%"></div></div><div class="ar-bar-count">${b.count}</div></div>`;
    }).join('');
}

function _renderARValChart(counts) {
    const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    const total = entries.reduce((s, e) => s + e[1], 0) || 1;
    const colors = { CHEAP: 'var(--green)', EXPENSIVE: 'var(--red)', FAIR: 'var(--blue)', MODERATE: 'var(--amber)' };
    let cumPct = 0;
    const segments = entries.map(([k, v]) => {
        const pct = v / total * 100;
        const color = colors[k.toUpperCase()] || 'var(--text-muted)';
        const seg = `${color} ${cumPct}% ${cumPct + pct}%`;
        cumPct += pct;
        return seg;
    });
    const legend = entries.map(([k, v]) => {
        const color = colors[k.toUpperCase()] || 'var(--text-muted)';
        return `<div class="ar-legend-item"><span class="ar-legend-dot" style="background:${color}"></span>${k} <strong>${v}</strong> <small>(${(v / total * 100).toFixed(0)}%)</small></div>`;
    }).join('');
    document.getElementById('arValChart').innerHTML =
        `<div class="ar-donut" style="background:conic-gradient(${segments.join(',')});"></div><div class="ar-legend">${legend}</div>`;
}

function _renderARSectorTable(sectors) {
    const sorted = [...sectors].sort((a, b) => {
        let va = a[_arSortKey], vb = b[_arSortKey];
        if (typeof va === 'string') { va = va.toLowerCase(); vb = (vb || '').toLowerCase(); }
        if (va == null) va = -Infinity;
        if (vb == null) vb = -Infinity;
        return _arSortAsc ? (va > vb ? 1 : -1) : (va < vb ? 1 : -1);
    });
    const tbody = document.getElementById('arSectorBody');
    tbody.innerHTML = sorted.map(s => {
        const pe = s.avg_pe != null ? s.avg_pe.toFixed(1) : '—';
        return `<tr><td><strong>${s.sector}</strong></td><td>${s.count}</td><td>${pe}</td><td>${s.cheap || 0}</td><td>${s.expensive || 0}</td><td>${s.buy || 0}</td><td>${s.sell || 0}</td><td>${s.hold || 0}</td></tr>`;
    }).join('');

    document.querySelectorAll('#arSectorTable th[data-sort]').forEach(th => {
        th.classList.toggle('ar-sort-active', th.dataset.sort === _arSortKey);
        th.onclick = () => {
            if (_arSortKey === th.dataset.sort) _arSortAsc = !_arSortAsc;
            else { _arSortKey = th.dataset.sort; _arSortAsc = false; }
            _renderARSectorTable(_arData.sector_summary);
        };
    });
}

function _renderARTop10(list, tbodyId) {
    const fmt = v => v != null ? Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—';
    const fmtCurrency = v => (v != null && v !== '' && !isNaN(v)) ? Number(v).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '—';
    const tbody = document.getElementById(tbodyId);
    if (!list || list.length === 0) { tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:20px;">No data</td></tr>'; return; }
    tbody.innerHTML = list.map(s => {
        const sig = s.recommendation === 'BUY' ? '<span class="pe-signal-badge pe-signal-buy">BUY</span>'
            : s.recommendation === 'SELL' ? '<span class="pe-signal-badge pe-signal-sell">SELL</span>'
            : s.recommendation === 'HOLD' ? '<span class="pe-signal-badge pe-signal-hold">HOLD</span>' : '';
        return `<tr><td><strong>${s.symbol}</strong>${s.company_name ? '<br><small style="color:var(--text-muted)">' + s.company_name + '</small>' : ''}</td><td>${fmt(s.pe)}</td><td>₹${fmtCurrency(s.cmp)}</td><td>${fmt(s.fy_eps)}</td><td>${s.sector || '—'}</td><td>${sig}</td></tr>`;
    }).join('');
}

(function initPEAnalysisControls() {
    document.addEventListener('DOMContentLoaded', () => {
        peInitMultiselects();
        peApplyColumnVisibility();
        peInitColumnsToggle();
        const filterInput = document.getElementById('peSymbolFilter');
        const refreshBtn = document.getElementById('peRefreshBtn');
        const fetchCmpBtn = document.getElementById('peFetchCmpBtn');
        const exportBtn = document.getElementById('peExportBtn');
        let _peFilterTimer = null;
        if (filterInput) filterInput.addEventListener('input', () => {
            clearTimeout(_peFilterTimer);
            _peFilterTimer = setTimeout(() => {
                peCurrentPage = 1;
                loadPEAnalysis();
            }, 300);
        });
        const showLimitSelect = document.getElementById('peShowLimit');
        if (showLimitSelect) showLimitSelect.addEventListener('change', () => { peCurrentPage = 1; loadPEAnalysis(); });
        peInitDateRangePicker();
        if (refreshBtn) refreshBtn.addEventListener('click', () => { loadPEFilterOptions(); loadPEAnalysis(false); });
        if (exportBtn) exportBtn.addEventListener('click', exportPEAnalysisToExcel);
        if (fetchCmpBtn) fetchCmpBtn.addEventListener('click', async () => {
            fetchCmpBtn.disabled = true;
            fetchCmpBtn.innerHTML = `${_SVG_LOADER_SPIN} Fetching...`;
            await loadPEAnalysis(true);
            fetchCmpBtn.disabled = false;
            fetchCmpBtn.innerHTML = `${_SVG_RUPEE} Fetch CMP`;
        });

        const uploadToggle = document.getElementById('peUploadToggleBtn');
        const uploadPanel = document.getElementById('peUploadPanel');
        if (uploadToggle && uploadPanel) {
            uploadToggle.addEventListener('click', () => {
                uploadPanel.style.display = uploadPanel.style.display === 'none' ? 'block' : 'none';
                if (uploadPanel.style.display !== 'none') refreshIcons(uploadPanel);
            });
        }

        // Formula modal — single button opens modal
        const formulaToggle = document.getElementById('peFormulaToggleBtn');
        const modal = document.getElementById('peFormulaModal');
        const modalClose = document.getElementById('peFormulaModalClose');
        const createToggle = document.getElementById('peFormulaCreateToggle');
        const createPanel = document.getElementById('peFormulaCreatePanel');
        const modalCancel = document.getElementById('peFormulaModalCancelBtn');

        function openFormulaModal() {
            renderPeFormulaList();
            if (createPanel) createPanel.style.display = 'none';
            modal.style.display = 'flex';
            if (modal) refreshIcons(modal);
        }
        function closeFormulaModal() { modal.style.display = 'none'; }

        if (formulaToggle) formulaToggle.addEventListener('click', openFormulaModal);
        if (modalClose) modalClose.addEventListener('click', closeFormulaModal);
        if (modal) modal.addEventListener('click', (e) => { if (e.target === modal) closeFormulaModal(); });

        if (createToggle && createPanel) {
            createToggle.addEventListener('click', () => {
                const isOpen = createPanel.style.display !== 'none';
                createPanel.style.display = isOpen ? 'none' : 'block';
                if (!isOpen) {
                    document.getElementById('pfName').value = '';
                    document.getElementById('pfQ1').value = 'Q1*4';
                    document.getElementById('pfQ2').value = '(Q1+Q2)*2';
                    document.getElementById('pfQ3').value = '(Q1+Q2+Q3)*4/3';
                    document.getElementById('pfQ4').value = 'FY';
                    const st = document.getElementById('peFormulaModalStatus');
                    if (st) st.style.display = 'none';
                }
            });
        }

        if (modalCancel && createPanel) {
            modalCancel.addEventListener('click', () => { createPanel.style.display = 'none'; });
        }

        // Formula creation form
        const form = document.getElementById('peFormulaForm');
        if (form) {
            form.addEventListener('submit', async (e) => {
                e.preventDefault();
                const saveBtn = document.getElementById('peFormulaModalSaveBtn');
                const st = document.getElementById('peFormulaModalStatus');
                const name = document.getElementById('pfName').value.trim();
                if (!name) return;
                saveBtn.disabled = true;
                saveBtn.textContent = 'Saving...';
                try {
                    const result = await createPeFormula(
                        name,
                        document.getElementById('pfQ1').value.trim(),
                        document.getElementById('pfQ2').value.trim(),
                        document.getElementById('pfQ3').value.trim(),
                        document.getElementById('pfQ4').value.trim()
                    );
                    if (result.success) {
                        createPanel.style.display = 'none';
                        await loadPeFormulas();
                        const newF = peFormulas.find(f => f.name === name);
                        if (newF && !peActiveFormulaIds.includes(newF.id)) {
                            peActiveFormulaIds.push(newF.id);
                            localStorage.setItem('peActiveFormulaIds', JSON.stringify(peActiveFormulaIds));
                        }
                        renderPeFormulaList();
                        renderPEAnalysis();
                    } else {
                        st.style.display = 'block';
                        st.style.background = '#7f1d1d'; st.style.color = '#fca5a5';
                        st.textContent = result.detail || 'Failed to save';
                    }
                } catch (err) {
                    st.style.display = 'block';
                    st.style.background = '#7f1d1d'; st.style.color = '#fca5a5';
                    st.textContent = 'Error: ' + err.message;
                } finally {
                    saveBtn.disabled = false;
                    saveBtn.textContent = 'Save Formula';
                }
            });
        }

        // Upload form
        const uploadForm = document.getElementById('peUploadForm');
        if (uploadForm) {
            uploadForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                const symbolInput = document.getElementById('peUploadSymbol');
                const fileInput = document.getElementById('peUploadFile');
                const exchangeSel = document.getElementById('peUploadExchange');
                const submitBtn = document.getElementById('peUploadSubmitBtn');
                const statusDiv = document.getElementById('peUploadStatus');

                const symbol = symbolInput.value.trim().toUpperCase();
                if (!symbol || !fileInput.files.length) return;

                submitBtn.disabled = true;
                submitBtn.innerHTML = `${_SVG_LOADER_SPIN} Processing...`;
                statusDiv.style.display = 'block';
                statusDiv.style.background = '#1e293b';
                statusDiv.style.color = '#94a3b8';
                statusDiv.textContent = `Processing ${fileInput.files[0].name} for ${symbol}...`;

                try {
                    const fd = new FormData();
                    fd.append('file', fileInput.files[0]);
                    fd.append('stock_symbol', symbol);
                    fd.append('exchange', exchangeSel.value);

                    const resp = await fetch('/api/upload_quarterly_pdf', { method: 'POST', body: fd });
                    const data = await resp.json();

                    if (data.success) {
                        statusDiv.style.background = '#064e3b';
                        statusDiv.style.color = '#6ee7b7';
                        statusDiv.textContent = `✓ ${data.stock_symbol}: ${data.periods_stored} period(s) saved. CMP & PE auto-fetched.`;
                        if (data.cmp_hint) {
                            statusDiv.style.background = '#78350f';
                            statusDiv.style.color = '#fcd34d';
                            statusDiv.textContent = `✓ ${data.stock_symbol}: ${data.periods_stored} period(s) saved. ⚠ ${data.cmp_hint}`;
                            showNotificationToast(data.cmp_hint, 'warning');
                        }
                        await loadPEAnalysis(false);
                        symbolInput.value = '';
                        fileInput.value = '';
                    } else {
                        statusDiv.style.background = '#7f1d1d';
                        statusDiv.style.color = '#fca5a5';
                        statusDiv.textContent = data.detail || 'Processing failed';
                    }
                } catch (err) {
                    statusDiv.style.background = '#7f1d1d';
                    statusDiv.style.color = '#fca5a5';
                    statusDiv.textContent = 'Error: ' + err.message;
                } finally {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = `${_SVG_CPU} Process & Save`;
                }
            });
        }
    });
})();

