/* FILE: src/App.tsx */
import React from 'react';
import { MainLayout } from './components/layout/MainLayout';

class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  componentDidCatch(error: Error) {
    console.error('App error:', error);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          width: '100vw', height: '100vh',
          background: '#FFF5F8', color: '#5E4B66',
          fontFamily: '"Noto Serif SC", serif', fontSize: 16,
        }}>
          人家遇到了一点小麻烦……刷新页面试试看？
        </div>
      );
    }
    return this.props.children;
  }
}

const App: React.FC = () => (
  <ErrorBoundary>
    <MainLayout />
  </ErrorBoundary>
);

export default App;
