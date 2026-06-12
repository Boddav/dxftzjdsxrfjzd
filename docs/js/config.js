// API Configuration
// Render.com backend URL
const API_CONFIG = {
    // Production backend (Render.com)
    baseURL: 'https://ai-trading-advisor-c4za.onrender.com',

    // For local development, uncomment below:
    // baseURL: 'http://localhost:5000'
};

// Helper function to make API calls
async function apiCall(endpoint, options = {}) {
    const url = `${API_CONFIG.baseURL}${endpoint}`;

    try {
        const response = await fetch(url, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            }
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        return await response.json();
    } catch (error) {
        console.error('API call failed:', error);
        throw error;
    }
}
