// API Configuration
// Change this URL to your deployed backend API
const API_CONFIG = {
    // For local development
    // baseURL: 'http://localhost:5000',

    // For production (change to your deployed backend URL)
    baseURL: 'https://your-backend-api.herokuapp.com',

    // Or use environment detection
    // baseURL: window.location.hostname === 'localhost'
    //     ? 'http://localhost:5000'
    //     : 'https://your-backend-api.herokuapp.com'
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
