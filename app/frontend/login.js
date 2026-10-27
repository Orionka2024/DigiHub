document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('loginForm');
    const errorMessage = document.getElementById('errorMessage');
    const submitBtn = form.querySelector('button[type="submit"]');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const username = document.getElementById('username').value.trim();
        const password = document.getElementById('password').value;
        
        errorMessage.style.display = 'none';
        errorMessage.textContent = '';
        
        submitBtn.disabled = true;
        const originalText = submitBtn.textContent;
        submitBtn.textContent = 'Signing in...';
        
        try {
            const res = await fetch('/api/login', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ username, password })
            });
            
            if (res.ok) {
                submitBtn.textContent = 'Success! Redirecting...';
                window.location.href = '/';
            } else {
                let detail = 'Login failed. Please check your credentials.';
                try {
                    const data = await res.json();
                    if (data && data.detail) detail = data.detail;
                } catch (_) {}
                errorMessage.textContent = detail;
                errorMessage.style.display = 'block';
                submitBtn.disabled = false;
                submitBtn.textContent = originalText;
            }
        } catch (err) {
            errorMessage.textContent = 'Network error. Please try again later.';
            errorMessage.style.display = 'block';
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
        }
    });
});
