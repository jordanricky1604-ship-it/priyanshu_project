document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('solve-form');
    const submitBtn = document.getElementById('submit-btn');
    const btnText = submitBtn.querySelector('.btn-text');
    const loader = submitBtn.querySelector('.loader');
    
    const resultsPanel = document.getElementById('results-panel');
    const resStatus = document.getElementById('res-status');
    const resLatency = document.getElementById('res-latency');
    const resToken = document.getElementById('res-token');
    const errorBox = document.getElementById('error-box');
    const copyBtn = document.getElementById('copy-btn');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        // UI Loading state
        submitBtn.disabled = true;
        btnText.classList.add('hidden');
        loader.classList.remove('hidden');
        resultsPanel.classList.add('hidden');
        errorBox.classList.add('hidden');

        // Gather data
        const url = document.getElementById('url').value;
        const captcha_type = parseInt(document.getElementById('captcha_type').value, 10);
        const visible_browser = document.getElementById('visible_browser').checked;

        try {
            const response = await fetch('/solve', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    url,
                    captcha_type,
                    visible_browser
                })
            });

            const data = await response.json();

            resultsPanel.classList.remove('hidden');

            if (response.ok && data.success) {
                resStatus.textContent = 'Solved';
                resStatus.className = 'value badge success';
                resLatency.textContent = `${Math.round(data.elapsed_ms)} ms`;
                resToken.textContent = data.token;
            } else {
                resStatus.textContent = 'Failed';
                resStatus.className = 'value badge error';
                resLatency.textContent = data.elapsed_ms ? `${Math.round(data.elapsed_ms)} ms` : '--';
                resToken.textContent = 'N/A';
                
                errorBox.textContent = data.error || data.detail || 'Unknown error occurred.';
                errorBox.classList.remove('hidden');
            }
        } catch (error) {
            resultsPanel.classList.remove('hidden');
            resStatus.textContent = 'Error';
            resStatus.className = 'value badge error';
            resLatency.textContent = '--';
            resToken.textContent = 'N/A';
            errorBox.textContent = 'Network error or daemon is offline.';
            errorBox.classList.remove('hidden');
        } finally {
            // Restore UI state
            submitBtn.disabled = false;
            btnText.classList.remove('hidden');
            loader.classList.add('hidden');
        }
    });

    copyBtn.addEventListener('click', () => {
        const textToCopy = resToken.textContent;
        if (textToCopy && textToCopy !== 'N/A' && textToCopy !== '...') {
            navigator.clipboard.writeText(textToCopy).then(() => {
                const originalSvg = copyBtn.innerHTML;
                copyBtn.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" stroke="#10b981" stroke-width="2" fill="none"><polyline points="20 6 9 17 4 12"></polyline></svg>';
                setTimeout(() => {
                    copyBtn.innerHTML = originalSvg;
                }, 2000);
            });
        }
    });
});
