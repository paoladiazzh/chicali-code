/**
 * Dashboard Frontend – WebSocket + Chart.js
 * Connects to the FastAPI backend for real-time log streaming and metrics updates.
 */

// ─── WebSocket Connection ────────────────────────────────────────────────────────
const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws`);

ws.onopen = () => appendLog('[ws] Connected to backend.', 'success');
ws.onclose = () => appendLog('[ws] Disconnected. Refresh to reconnect.', 'error');
ws.onerror = () => appendLog('[ws] Connection error.', 'error');

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'log') {
        appendLog(data.message, data.level);
    } else if (data.type === 'metrics') {
        updateMetrics(data.data);
    }
};

// ─── Log Terminal ────────────────────────────────────────────────────────────────
const terminal = document.getElementById('log-terminal');

function appendLog(msg, level = 'info') {
    const line = document.createElement('div');
    line.className = `log-${level}`;
    const ts = new Date().toLocaleTimeString();
    line.textContent = `[${ts}] ${msg}`;
    terminal.appendChild(line);
    terminal.scrollTop = terminal.scrollHeight;
}

function clearTerminal() {
    terminal.innerHTML = '';
    appendLog('[system] Terminal cleared.', 'info');
}

// ─── KPI Updates ─────────────────────────────────────────────────────────────────
function updateMetrics(data) {
    document.getElementById('kpi-tokens').textContent = data.total_tokens.toLocaleString();
    document.getElementById('kpi-input-tokens').textContent = data.total_prompt_tokens.toLocaleString();
    document.getElementById('kpi-output-tokens').textContent = data.total_completion_tokens.toLocaleString();
    document.getElementById('kpi-cost').textContent = `$${data.total_cost.toFixed(6)}`;
    document.getElementById('kpi-calls').textContent = data.call_count;

    // Update charts with history
    if (data.history && data.history.length > 0) {
        updateTokenChart(data.history);
    }
}

function updateMappingKPIs(successful, total) {
    document.getElementById('kpi-mappings').textContent = successful;
    const accuracy = total > 0 ? ((successful / total) * 100).toFixed(1) + '%' : '—';
    document.getElementById('kpi-accuracy').textContent = accuracy;
    updateAccuracyChart(successful, total - successful);
}

// ─── Charts ──────────────────────────────────────────────────────────────────────
// Token Usage Line Chart
const tokenCtx = document.getElementById('chart-tokens').getContext('2d');
const tokenChart = new Chart(tokenCtx, {
    type: 'line',
    data: {
        labels: [],
        datasets: [
            {
                label: 'Input Tokens',
                data: [],
                borderColor: '#90cdf4',
                backgroundColor: 'rgba(144, 205, 244, 0.1)',
                fill: true,
                tension: 0.3,
            },
            {
                label: 'Output Tokens',
                data: [],
                borderColor: '#68d391',
                backgroundColor: 'rgba(104, 211, 145, 0.1)',
                fill: true,
                tension: 0.3,
            },
        ],
    },
    options: {
        responsive: true,
        plugins: {
            legend: { labels: { color: '#a0aec0', font: { size: 11 } } },
        },
        scales: {
            x: { ticks: { color: '#718096' }, grid: { color: '#2d3748' } },
            y: { ticks: { color: '#718096' }, grid: { color: '#2d3748' } },
        },
    },
});

function updateTokenChart(history) {
    tokenChart.data.labels = history.map((_, i) => `Call ${i + 1}`);
    tokenChart.data.datasets[0].data = history.map(h => h.prompt_tokens);
    tokenChart.data.datasets[1].data = history.map(h => h.completion_tokens);
    tokenChart.update();
}

// Accuracy Doughnut Chart
const accCtx = document.getElementById('chart-accuracy').getContext('2d');
const accuracyChart = new Chart(accCtx, {
    type: 'doughnut',
    data: {
        labels: ['Successful', 'Failed'],
        datasets: [{
            data: [1, 0],
            backgroundColor: ['#68d391', '#fc8181'],
            borderWidth: 0,
        }],
    },
    options: {
        responsive: true,
        cutout: '65%',
        plugins: {
            legend: { labels: { color: '#a0aec0', font: { size: 11 } } },
        },
    },
});

function updateAccuracyChart(successful, failed) {
    accuracyChart.data.datasets[0].data = [successful, failed];
    accuracyChart.update();
}

// ─── API Calls ───────────────────────────────────────────────────────────────────
async function apiCall(endpoint, method = 'POST') {
    try {
        appendLog(`Calling ${endpoint}...`, 'info');
        const res = await fetch(endpoint, { method });
        const data = await res.json();
        if (data.status === 'error') {
            appendLog(`Error: ${data.message}`, 'error');
        }
        return data;
    } catch (err) {
        appendLog(`Request failed: ${err.message}`, 'error');
        return null;
    }
}

// ─── Records Table ───────────────────────────────────────────────────────────
let records = [];

function addMappingRecords(mapping) {
    const now = new Date().toLocaleString();
    Object.entries(mapping).forEach(([key, val]) => {
        records.push({
            origin: key,
            selector: val.destination_selector || '—',
            value: '—',
            status: 'mapped',
            timestamp: now,
        });
    });
    renderTable();
}

function addAutomationRecords(payload) {
    const now = new Date().toLocaleString();
    Object.entries(payload).forEach(([selector, value]) => {
        records.push({
            origin: '—',
            selector: selector,
            value: value,
            status: 'filled',
            timestamp: now,
        });
    });
    renderTable();
}

function renderTable() {
    const tbody = document.getElementById('records-tbody');
    document.getElementById('record-count').textContent = `${records.length} records`;

    if (records.length === 0) {
        tbody.innerHTML = '<tr class="text-gray-500"><td colspan="6" class="px-4 py-6 text-center">No records yet.</td></tr>';
        return;
    }

    tbody.innerHTML = records.map((r, i) => {
        const statusBadge = r.status === 'filled'
            ? '<span class="px-2 py-0.5 text-xs rounded-full bg-green-900/50 text-green-300">✓ Filled</span>'
            : r.status === 'failed'
            ? '<span class="px-2 py-0.5 text-xs rounded-full bg-red-900/50 text-red-300">✗ Failed</span>'
            : '<span class="px-2 py-0.5 text-xs rounded-full bg-blue-900/50 text-blue-300">◉ Mapped</span>';
        return `<tr class="hover:bg-gray-700/30">
            <td class="px-4 py-2 text-gray-400">${i + 1}</td>
            <td class="px-4 py-2 text-blue-300 font-mono text-xs">${r.origin}</td>
            <td class="px-4 py-2 text-purple-300 font-mono text-xs">${r.selector}</td>
            <td class="px-4 py-2 text-gray-200">${r.value}</td>
            <td class="px-4 py-2">${statusBadge}</td>
            <td class="px-4 py-2 text-gray-500 text-xs">${r.timestamp}</td>
        </tr>`;
    }).join('');
}

// ─── API Actions ─────────────────────────────────────────────────────────────────
async function launchBrowser() {
    await apiCall('/api/launch-browser');
}

async function runObservation() {
    const result = await apiCall('/api/observe');
    if (result && result.mapping) {
        addMappingRecords(result.mapping);
        fetchMetrics();
    }
}

async function runAutomation() {
    const result = await apiCall('/api/automate');
    if (result && result.status === 'ok') {
        addAutomationRecords(result.payload);
        updateMappingKPIs(result.filled, result.filled + result.failed);
        fetchMetrics();
    }
}

async function resetLogs() {
    await apiCall('/api/reset-logs');
}

async function fetchMetrics() {
    const data = await apiCall('/api/metrics', 'GET');
    if (data) {
        updateMetrics(data);
        if (data.successful_mappings !== undefined) {
            updateMappingKPIs(data.successful_mappings, data.total_fields_attempted);
        }
    }
}

// Initial metrics fetch
fetchMetrics();
