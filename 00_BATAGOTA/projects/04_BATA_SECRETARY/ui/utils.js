/**
 * BATA Secretary - API & JWT 유틸리티
 * 모든 HTML 파일에서 import하여 사용할 수 있는 공용 함수들
 */

const API_BASE = 'http://127.0.0.1:8000';

/**
 * localStorage에서 JWT 토큰 가져오기
 */
function getAuthToken() {
  return localStorage.getItem('bata_access_token');
}

/**
 * JWT 토큰을 포함한 fetch 요청
 * @param {string} url - API 엔드포인트 (절대 경로 또는 상대 경로)
 * @param {object} options - fetch 옵션
 * @returns {Promise}
 */
async function apiCall(url, options = {}) {
  const token = getAuthToken();
  
  // 상대 경로인 경우 절대 경로로 변환
  const fullUrl = url.startsWith('http') ? url : API_BASE + url;
  
  // Authorization 헤더 추가
  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  };
  
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  
  return fetch(fullUrl, {
    ...options,
    headers,
  });
}

/**
 * WebSocket 연결 시 JWT 토큰을 URL 쿼리 파라미터로 전달
 * @param {string} path - WebSocket 경로
 * @returns {string} 토큰을 포함한 WebSocket URL
 */
function getWebSocketURL(path) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const token = getAuthToken();
  const baseURL = `${protocol}//127.0.0.1:8000${path}`;
  
  if (token) {
    return `${baseURL}?token=${encodeURIComponent(token)}`;
  }
  
  return baseURL;
}

/**
 * 현재 사용자 정보 가져오기
 * @returns {object} 사용자 정보 또는 null
 */
function getCurrentUser() {
  const user = localStorage.getItem('bata_current_user');
  return user ? JSON.parse(user) : null;
}

/**
 * 로그인 여부 확인 및 로그인 페이지로 리다이렉트
 */
function requireAuth() {
  const token = getAuthToken();
  const user = getCurrentUser();
  
  if (!token || !user) {
    window.location.href = 'login.html';
    return false;
  }
  
  return true;
}

/**
 * 로그아웃 (localStorage 정리)
 */
function logout() {
  localStorage.removeItem('bata_access_token');
  localStorage.removeItem('bata_token_type');
  localStorage.removeItem('bata_current_user');
  localStorage.removeItem('bata_sessions');
  localStorage.removeItem('bata_workflow_history');
  window.location.href = 'login.html';
}
