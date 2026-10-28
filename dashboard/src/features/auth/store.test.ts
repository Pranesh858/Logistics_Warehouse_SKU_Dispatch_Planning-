/**
 * What each role is offered.
 *
 * The server enforces every one of these rules, which is where enforcement belongs. These tests are about
 * the other half: not offering a person a button that will come back 403, and never widening a planner's
 * view past their own warehouse. A bug here is silent - the page simply shows the wrong thing to the wrong
 * person, and nothing throws.
 */
import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { signInAs, signOut, user } from '@/test/render';
import { useAuth, useCan, useScope } from './store';

beforeEach(() => signOut());

describe('what the signed-in person may do', () => {
  it('lets an admin edit, administer and switch warehouse', () => {
    signInAs('admin');
    const { result } = renderHook(() => useCan());
    expect(result.current).toEqual({ edit: true, admin: true, switchWarehouse: true });
  });

  it('lets a planner edit but not administer, and pins them to one warehouse', () => {
    signInAs('planner', 'WH01');
    const { result } = renderHook(() => useCan());
    expect(result.current.edit).toBe(true);
    expect(result.current.admin).toBe(false);
    expect(result.current.switchWarehouse).toBe(false);
  });

  it('gives a viewer nothing to press', () => {
    signInAs('viewer');
    const { result } = renderHook(() => useCan());
    expect(result.current).toEqual({ edit: false, admin: false, switchWarehouse: true });
  });

  it('offers nothing at all when nobody is signed in', () => {
    const { result } = renderHook(() => useCan());
    expect(result.current).toEqual({ edit: false, admin: false, switchWarehouse: false });
  });
});

describe('which warehouse the pages show', () => {
  it('shows all warehouses to an admin who has not narrowed the view', () => {
    signInAs('admin');
    expect(renderHook(() => useScope()).result.current).toBeNull();
  });

  it('narrows to the warehouse an admin picked', () => {
    signInAs('admin');
    useAuth.getState().setViewWarehouse('WH04');
    expect(renderHook(() => useScope()).result.current).toBe('WH04');
  });

  it('keeps a planner on their own warehouse', () => {
    signInAs('planner', 'WH02');
    expect(renderHook(() => useScope()).result.current).toBe('WH02');
  });

  it('ignores an attempt to point a planner at another warehouse', () => {
    signInAs('planner', 'WH02');
    useAuth.getState().setViewWarehouse('WH05');
    expect(renderHook(() => useScope()).result.current).toBe('WH02');
  });
});

describe('signing out', () => {
  it('clears the session and the narrowed view', () => {
    signInAs('admin');
    useAuth.getState().setViewWarehouse('WH03');
    useAuth.getState().signOut();
    const s = useAuth.getState();
    expect(s.token).toBeNull();
    expect(s.user).toBeNull();
    expect(s.viewWarehouse).toBeNull();
  });

  it('does not leave the session behind in storage', () => {
    signInAs('admin');
    useAuth.getState().signIn('t', { ...useAuth.getState().user! });
    expect(window.localStorage.getItem('dispatch-planner-session')).not.toBeNull();
    useAuth.getState().signOut();
    expect(window.localStorage.getItem('dispatch-planner-session')).toBeNull();
  });

  it('survives storage being blocked', () => {
    const original = window.localStorage.setItem;
    window.localStorage.setItem = () => { throw new Error('blocked'); };
    try {
      expect(() => useAuth.getState().signIn('t', user('admin'))).not.toThrow();
      expect(useAuth.getState().token).toBe('t');       // the session still works for this tab
    } finally {
      window.localStorage.setItem = original;
    }
  });
});