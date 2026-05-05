import React from 'react';
import FloatingChatbot from './components/FloatingChatbot';

function App() {
  return (
    <div className="App" style={{ 
      minHeight: '100vh', 
      display: 'flex', 
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'linear-gradient(135deg, #f3f4f6 0%, #e5e7eb 100%)',
      fontFamily: 'Inter, system-ui, Avenir, Helvetica, Arial, sans-serif'
    }}>
      <header style={{ textAlign: 'center', marginBottom: '2rem' }}>
        <h1 style={{ fontSize: '3rem', fontWeight: '800', color: '#1f2937', marginBottom: '1rem' }}>
          HRMS AI Assistant
        </h1>
        <p style={{ fontSize: '1.25rem', color: '#6b7280' }}>
          Welcome to the FirstClick HRMS Chatbot Interface.
        </p>
      </header>
      
      <main style={{ maxWidth: '800px', width: '90%', background: 'white', padding: '3rem', borderRadius: '1.5rem', boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1)' }}>
        <h2 style={{ fontSize: '1.5rem', fontWeight: '700', color: '#374151', marginBottom: '1.5rem' }}>
          Dashboard Overview
        </h2>
        <p style={{ color: '#4b5563', lineHeight: '1.6' }}>
          This is a demonstration of the HRMS AI Chatbot integration. You can interact with the chatbot using the button in the bottom-right corner.
        </p>
        <div style={{ marginTop: '2rem', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1.5rem' }}>
          <div style={{ padding: '1.5rem', background: '#f9fafb', borderRadius: '1rem', border: '1px solid #e5e7eb' }}>
            <h3 style={{ fontSize: '1.125rem', fontWeight: '600', color: '#111827', marginBottom: '0.5rem' }}>Attendance</h3>
            <p style={{ fontSize: '0.875rem', color: '#6b7280' }}>Monitor employee presence and punch-in times.</p>
          </div>
          <div style={{ padding: '1.5rem', background: '#f9fafb', borderRadius: '1rem', border: '1px solid #e5e7eb' }}>
            <h3 style={{ fontSize: '1.125rem', fontWeight: '600', color: '#111827', marginBottom: '0.5rem' }}>Leave Requests</h3>
            <p style={{ fontSize: '0.875rem', color: '#6b7280' }}>Manage and approve leave applications.</p>
          </div>
          <div style={{ padding: '1.5rem', background: '#f9fafb', borderRadius: '1rem', border: '1px solid #e5e7eb' }}>
            <h3 style={{ fontSize: '1.125rem', fontWeight: '600', color: '#111827', marginBottom: '0.5rem' }}>Payroll</h3>
            <p style={{ fontSize: '0.875rem', color: '#6b7280' }}>Automated salary calculations and reports.</p>
          </div>
        </div>
      </main>

      <FloatingChatbot role="Admin" />
    </div>
  );
}

export default App;
