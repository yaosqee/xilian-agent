import React, { useEffect, useState } from 'react';
import { MainLayout } from './components/layout/MainLayout';
import OnboardingPage from './components/OnboardingPage';

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

const App: React.FC = () => {
  const [hasKey, setHasKey] = useState<boolean | null>(null); // null = loading

  useEffect(() => {
    fetch('/api/config/check')
      .then(r => {
        if (!r.ok) return true; // 端点不存在 → 正常模式
        return r.json().then(d => d.has_api_key === true);
      })
      .then(has => setHasKey(has))
      .catch(() => setHasKey(true)); // 网络不通 → 正常模式兜底
  }, []);

  if (hasKey === null) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        width: '100vw', height: '100vh',
        background: '#FFF5F8',
      }}>
        <p style={{ color: '#C4B5CF', fontSize: 14 }}>♪</p>
      </div>
    );
  }

  if (!hasKey) {
    return <OnboardingPage />;
  }

  return (
    <ErrorBoundary>
      <MainLayout />
    </ErrorBoundary>
  );
};

export default App;
