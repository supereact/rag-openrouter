import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { UserManagementPanel } from './AdminPanel'
import { api } from './api'
import type { AdminUser } from './types'

vi.mock('./api', async original => {
  const actual = await original<typeof import('./api')>()
  return {...actual, api:{...actual.api, adminUsers:vi.fn(),adminInvitations:vi.fn(),adminInvite:vi.fn(),adminUpdateUser:vi.fn(),adminRevokeSessions:vi.fn()}}
})
const users: AdminUser[] = [
  {id:1,username:'self-admin',email:'admin@example.org',role:'admin',is_active:true,created_at:'2026-10-16T00:00:00Z'},
  {id:2,username:'editor',email:'editor@example.org',role:'editor',is_active:true,created_at:'2026-10-16T00:00:00Z'},
  {id:3,username:'disabled-reader',email:null,role:'reader',is_active:false,created_at:'2026-10-16T00:00:00Z'},
  ...Array.from({length:22},(_,i):AdminUser => ({id:i+4,username:`reader-${i}`,email:`person${i}@example.org`,role:'reader',is_active:true,created_at:'2026-10-15T00:00:00Z'})),
]
const props = {apiKey:'key',selfUserId:1,onUnauthorized:vi.fn()}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.adminUsers).mockResolvedValue(users)
  vi.mocked(api.adminInvitations).mockResolvedValue([])
  vi.mocked(api.adminUpdateUser).mockResolvedValue(users[1])
  vi.mocked(api.adminRevokeSessions).mockResolvedValue(undefined)
})
afterEach(cleanup)

it('filters by username/email, role and status, with shared pagination controls', async () => {
  render(<UserManagementPanel {...props}/>)
  await screen.findByText('self-admin · You')
  expect(screen.getAllByRole('columnheader').map(el => el.textContent)).toEqual(['Username','Email','Role','Status','Created','Actions'])
  expect(within(screen.getByRole('table',{name:'Users'})).getAllByRole('row')).toHaveLength(21)
  fireEvent.click(screen.getByRole('button',{name:'Next'}))
  expect(screen.getByText('reader-21')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Search users'),{target:{value:'editor@example'}})
  expect(screen.getByRole('cell',{name:'editor'})).toBeInTheDocument()
  expect(screen.queryByText('reader-21')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Search users'),{target:{value:''}})
  fireEvent.change(screen.getByLabelText('Filter user role'),{target:{value:'reader'}})
  fireEvent.change(screen.getByLabelText('Filter user status'),{target:{value:'disabled'}})
  expect(screen.getByText('disabled-reader')).toBeInTheDocument()
  expect(screen.queryByRole('cell',{name:'editor'})).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Rows per page'),{target:{value:'100'}})
  expect(screen.getByText('1 results · Page 1 of 1')).toBeInTheDocument()
})

it('preserves self safeguards, role changes, activation and session revocation', async () => {
  render(<UserManagementPanel {...props}/>)
  await screen.findByText('self-admin · You')
  const selfRow = screen.getByText('self-admin · You').closest('tr')!
  expect(screen.getByLabelText('Role for self-admin')).toBeDisabled()
  expect(within(selfRow).getByRole('button',{name:'Disable'})).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Role for editor'),{target:{value:'reader'}})
  await waitFor(() => expect(api.adminUpdateUser).toHaveBeenCalledWith('key',2,{role:'reader'}))
  await screen.findByText('Updated editor. Their browser sessions have been revoked.')
  fireEvent.click(within(screen.getByText('disabled-reader').closest('tr')!).getByRole('button',{name:'Enable'}))
  await waitFor(() => expect(api.adminUpdateUser).toHaveBeenCalledWith('key',3,{is_active:true}))
  await screen.findByText('Updated disabled-reader. Their browser sessions have been revoked.')
  fireEvent.click(within(screen.getByRole('cell',{name:'editor'}).closest('tr')!).getByRole('button',{name:'Disable'}))
  await waitFor(() => expect(api.adminUpdateUser).toHaveBeenCalledWith('key',2,{is_active:false}))
  await screen.findByText('Updated editor. Their browser sessions have been revoked.')
  fireEvent.click(within(selfRow).getByRole('button',{name:'Revoke sessions'}))
  await waitFor(() => expect(api.adminRevokeSessions).toHaveBeenCalledWith('key',1))
})

it('preserves invitation creation, one-time code and invitation statuses', async () => {
  vi.mocked(api.adminInvite).mockResolvedValue({invitation_id:7,invitation_code:'synthetic-one-time-code',email:'new@example.org',role:'editor',expires_in_hours:24})
  vi.mocked(api.adminInvitations).mockResolvedValue([{id:7,email:'new@example.org',role:'editor',created_at:'2026-10-16',expires_at:'2099-10-17',used_at:null}])
  const view = render(<UserManagementPanel {...props}/>)
  await screen.findByText('Pending')
  fireEvent.change(screen.getByLabelText('Invitee email'),{target:{value:'new@example.org'}})
  fireEvent.change(screen.getByLabelText('Invitation role'),{target:{value:'editor'}})
  fireEvent.click(screen.getByRole('button',{name:'Create invitation'}))
  await screen.findByText('synthetic-one-time-code')
  expect(api.adminInvite).toHaveBeenCalledWith('key','new@example.org','editor')
  view.unmount()
  render(<UserManagementPanel {...props}/>)
  expect(screen.queryByText('synthetic-one-time-code')).not.toBeInTheDocument()
})
