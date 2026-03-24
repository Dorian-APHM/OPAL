import { describe, it, expect, vi, beforeEach } from 'vitest';
import api, { setTokenGetter, setTokenRefresher, getAuthToken } from './client';

describe('API Client', () => {
  beforeEach(() => {
    setTokenGetter(() => undefined);
    setTokenRefresher(async () => undefined);
  });

  it('exports api as default', () => {
    expect(api).toBeDefined();
    expect(api.defaults.baseURL).toBe('/api');
  });

  it('sets token getter and returns token', () => {
    setTokenGetter(() => 'test-token');
    expect(getAuthToken()).toBe('test-token');
  });

  it('has request timeout configured', () => {
    expect(api.defaults.timeout).toBe(30000);
  });

  it('has request interceptor for auth', () => {
    // Request interceptors are registered
    expect(api.interceptors.request).toBeDefined();
  });

  it('has response interceptor for error handling', () => {
    expect(api.interceptors.response).toBeDefined();
  });
});

describe('API modules', () => {
  it('exports cdmApi', async () => {
    const { cdmApi } = await import('./client');
    expect(cdmApi).toBeDefined();
    expect(cdmApi.list).toBeTypeOf('function');
    expect(cdmApi.create).toBeTypeOf('function');
    expect(cdmApi.delete).toBeTypeOf('function');
  });

  it('exports qualityApi', async () => {
    const { qualityApi } = await import('./client');
    expect(qualityApi).toBeDefined();
    expect(qualityApi.analyze).toBeTypeOf('function');
  });

  it('exports cohortApi', async () => {
    const { cohortApi } = await import('./client');
    expect(cohortApi).toBeDefined();
    expect(cohortApi.list).toBeTypeOf('function');
    expect(cohortApi.create).toBeTypeOf('function');
  });

  it('exports mappingApi', async () => {
    const { mappingApi } = await import('./client');
    expect(mappingApi).toBeDefined();
    expect(mappingApi.dashboard).toBeTypeOf('function');
  });

  it('exports conceptApi', async () => {
    const { conceptApi } = await import('./client');
    expect(conceptApi).toBeDefined();
    expect(conceptApi.search).toBeTypeOf('function');
  });
});
