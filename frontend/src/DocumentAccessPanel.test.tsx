import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import DocumentAccessPanel from './DocumentAccessPanel'
import { api, ApiError } from './api'
import type { DocumentAccess } from './types'

vi.mock('./api', async original => {
  const actual = await original<typeof import('./api')>()
  return {...actual, api:{...actual.api, documentAccess:vi.fn(), updateDocumentAccess:vi.fn()}}
})
const directory: DocumentAccess = {users:[
  {id:1, username:'owner', email:null, is_active:true, shared:false, automatic_access:'owner'},
  {id:2, username:'admin', email:null, is_active:true, shared:false, automatic_access:'admin'},
  {id:3, username:'existing', email:'old@example.org', is_active:true, shared:true, automatic_access:null},
  {id:4, username:'new-one', email:'one@example.org', is_active:true, shared:false, automatic_access:null},
  {id:5, username:'new-two', email:'two@example.org', is_active:true, shared:false, automatic_access:null},
  {id:6, username:'inactive', email:null, is_active:false, shared:false, automatic_access:null},
  {id:7, username:'inactive-shared', email:null, is_active:false, shared:true, automatic_access:null},
]}
const props = {apiKey:'key', documentId:11, title:'Guide.pdf', onUnauthorized:vi.fn(), onSaved:vi.fn(), onCancel:vi.fn()}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.documentAccess).mockReset().mockResolvedValue(directory)
  vi.mocked(api.updateDocumentAccess).mockReset().mockResolvedValue(directory)
})
afterEach(cleanup)

it('preselects existing recipients, preserves selection while searching, and submits multiple deltas', async () => {
  render(<DocumentAccessPanel {...props}/>)
  expect(await screen.findByLabelText('Access for existing')).toBeChecked()
  expect(screen.getByLabelText('Access for owner')).toBeDisabled()
  expect(screen.getByLabelText('Access for admin')).toBeDisabled()
  expect(screen.getByLabelText('Access for inactive')).toBeDisabled()
  fireEvent.click(screen.getByLabelText('Access for existing'))
  fireEvent.click(screen.getByLabelText('Access for inactive-shared'))
  fireEvent.change(screen.getByLabelText('Search users to share with'), {target:{value:'one@example'}})
  fireEvent.click(screen.getByLabelText('Access for new-one'))
  fireEvent.change(screen.getByLabelText('Search users to share with'), {target:{value:'new-two'}})
  fireEvent.click(screen.getByLabelText('Access for new-two'))
  fireEvent.change(screen.getByLabelText('Search users to share with'), {target:{value:''}})
  expect(screen.getByLabelText('Access for new-one')).toBeChecked()
  fireEvent.click(screen.getByRole('button', {name:'Save changes'}))
  await waitFor(() => expect(props.onSaved).toHaveBeenCalledOnce())
  expect(api.updateDocumentAccess).toHaveBeenCalledWith('key',11,{grant_user_ids:[4,5],revoke_user_ids:[3,7]})
  expect(api.documentAccess).toHaveBeenCalledOnce()
})

it('Cancel discards edits without issuing a write', async () => {
  render(<DocumentAccessPanel {...props}/>)
  fireEvent.click(await screen.findByLabelText('Access for new-one'))
  fireEvent.click(screen.getByRole('button',{name:'Cancel'}))
  expect(props.onCancel).toHaveBeenCalledOnce()
  expect(api.updateDocumentAccess).not.toHaveBeenCalled()
})

it.each([401,403])('clears protected content on save HTTP %s', async status => {
  vi.mocked(api.updateDocumentAccess).mockRejectedValue(new ApiError(status,'Denied'))
  render(<DocumentAccessPanel {...props}/>)
  fireEvent.click(await screen.findByLabelText('Access for new-one'))
  fireEvent.click(screen.getByRole('button',{name:'Save changes'}))
  await screen.findByRole('alert')
  expect(screen.queryByLabelText('Access for existing')).not.toBeInTheDocument()
  expect(props.onUnauthorized).toHaveBeenCalledTimes(status === 401 ? 1 : 0)
  expect(props.onSaved).not.toHaveBeenCalled()
})

it('retries failed reads and keeps edits after an ordinary save failure', async () => {
  vi.mocked(api.documentAccess).mockRejectedValueOnce(new Error('Read unavailable'))
  vi.mocked(api.updateDocumentAccess).mockRejectedValueOnce(new Error('Save unavailable'))
  render(<DocumentAccessPanel {...props}/>)
  fireEvent.click(await screen.findByRole('button',{name:'Retry loading access'}))
  fireEvent.click(await screen.findByLabelText('Access for new-one'))
  fireEvent.click(screen.getByRole('button',{name:'Save changes'}))
  await screen.findByText('Save unavailable')
  expect(screen.getByLabelText('Access for new-one')).toBeChecked()
})

it.each([{apiKey:'key', documentId:12}, {apiKey:'new-session', documentId:11}])('resets drafts and ignores late saves after document/session changes: %o', async next => {
  let finish!: (value:DocumentAccess) => void
  vi.mocked(api.updateDocumentAccess).mockReturnValueOnce(new Promise(resolve => {finish=resolve}))
  const view = render(<DocumentAccessPanel {...props}/>)
  fireEvent.click(await screen.findByLabelText('Access for new-one'))
  fireEvent.click(screen.getByRole('button',{name:'Save changes'}))
  view.rerender(<DocumentAccessPanel {...props} {...next}/>)
  expect(await screen.findByLabelText('Access for new-one')).not.toBeChecked()
  await act(async () => finish(directory))
  expect(props.onSaved).not.toHaveBeenCalled()
})
