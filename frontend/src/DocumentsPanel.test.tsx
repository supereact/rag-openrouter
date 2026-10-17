import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import DocumentsPanel from './DocumentsPanel'
import { api, ApiError } from './api'
import type { DocumentLibrary, LibraryRow } from './types'

vi.mock('./api', async original => {
  const actual = await original<typeof import('./api')>()
  return {...actual, api:{...actual.api, library:vi.fn(), remove:vi.fn(), removeJob:vi.fn(),
    documentAccess:vi.fn(), updateDocumentAccess:vi.fn(), uploadQueued:vi.fn(), reindex:vi.fn()}}
})
const row: LibraryRow = {kind:'document',id:'11',title:'Guide.pdf',created_at:'2026-10-16T00:00:00Z',status:'indexed',owner_user_id:2,can_manage:true,assigned_users:[],error:null}
const listing: DocumentLibrary = {items:[row],total:1,page:1,page_size:20,pages:1}
const props = {session:{key:'key',identity:{user_id:2,tenant_id:7,role:'editor' as const,username:'owner'}},onUnauthorized:vi.fn()}
beforeEach(() => {
  window.history.replaceState({}, '', '/documents')
  vi.clearAllMocks()
  vi.mocked(api.library).mockReset().mockResolvedValue(listing)
  vi.mocked(api.remove).mockResolvedValue(undefined)
  vi.mocked(api.removeJob).mockResolvedValue(undefined)
  vi.spyOn(window,'confirm').mockReturnValue(true)
  vi.mocked(api.documentAccess).mockResolvedValue({users:[{id:3,username:'colleague',email:null,is_active:true,shared:false,automatic_access:null}]})
})
afterEach(() => {cleanup(); vi.restoreAllMocks(); vi.useRealTimers()})

it('binds server filters to the URL, resets pages, and follows query history', async () => {
  window.history.replaceState({}, '', '/documents?page=3&page_size=50&q=policy&status=failed&file_type=pdf')
  vi.mocked(api.library).mockImplementation(async (_, query) => ({...listing,page:Number(query.get('page')),page_size:Number(query.get('page_size')),total:160,pages:4}))
  render(<DocumentsPanel {...props}/>)
  await screen.findByText('Guide.pdf')
  expect(screen.getByLabelText('Filter documents')).toHaveValue('policy')
  fireEvent.change(screen.getByLabelText('Document status'),{target:{value:'indexed'}})
  await waitFor(() => expect(api.library).toHaveBeenCalledTimes(2))
  expect(new URLSearchParams(window.location.search).get('page')).toBe('1')
  expect(new URLSearchParams(window.location.search).get('q')).toBe('policy')
  fireEvent.change(screen.getByLabelText('Rows per page'),{target:{value:'100'}})
  await waitFor(() => expect(api.library).toHaveBeenCalledTimes(3))
  act(() => window.history.back())
  await waitFor(() => expect(screen.getByLabelText('Rows per page')).toHaveValue('50'))
})

it('polls without overlapping reads, retains drafts and data after refresh failure', async () => {
  vi.useFakeTimers()
  await act(async () => {render(<DocumentsPanel {...props}/>)})
  await act(async () => {fireEvent.click(screen.getByLabelText('Manage access for Guide.pdf'))})
  fireEvent.click(screen.getByLabelText('Access for colleague'))
  const checkbox = screen.getByLabelText('Access for colleague')
  checkbox.focus()
  const table = screen.getByRole('table', {name:'Document library'})
  const documentRow = screen.getByText('Guide.pdf').closest('tr')
  const status = screen.getByText('Documents update automatically.')
  let reject!: (error:Error) => void
  vi.mocked(api.library).mockReturnValueOnce(new Promise((_, fail) => {reject=fail}))
  act(() => vi.advanceTimersByTime(3500))
  expect(api.library).toHaveBeenCalledTimes(2)
  expect(screen.getByRole('button',{name:'Refresh documents'})).toBeEnabled()
  expect(screen.getByLabelText('Delete Guide.pdf')).toBeEnabled()
  expect(screen.getByLabelText('Select documents to upload')).toBeEnabled()
  expect(screen.getByLabelText('Rows per page')).toBeEnabled()
  expect(screen.getByRole('table', {name:'Document library'})).toBe(table)
  expect(screen.getByText('Guide.pdf').closest('tr')).toBe(documentRow)
  expect(screen.getByText('Documents update automatically.')).toBe(status)
  expect(screen.queryByText('Refreshing documents…')).not.toBeInTheDocument()
  expect(checkbox).toHaveFocus()
  act(() => vi.advanceTimersByTime(7000))
  expect(api.library).toHaveBeenCalledTimes(2)
  await act(async () => reject(new Error('Temporary read failure')))
  expect(screen.getByText(/Previously loaded documents may be out of date/)).toBeInTheDocument()
  expect(screen.getByLabelText('Access for colleague')).toBeChecked()
  await act(async () => vi.advanceTimersByTime(3500))
  expect(api.library).toHaveBeenCalledTimes(3)
  expect(screen.getByLabelText('Access for colleague')).toBeChecked()
  expect(checkbox).toHaveFocus()
})

it('updates upload status in place while background polling preserves the document row', async () => {
  vi.useFakeTimers()
  const job: LibraryRow = {...row, kind:'upload', id:'job', title:'Import.md', status:'queued', assigned_users:null}
  vi.mocked(api.library).mockResolvedValueOnce({...listing,items:[row,job]})
    .mockResolvedValue({...listing,items:[row,{...job,status:'processing'}]})
  await act(async () => {render(<DocumentsPanel {...props}/>)})
  const documentRow = screen.getByText('Guide.pdf').closest('tr')
  const jobRow = screen.getByText('Import.md').closest('tr')
  await act(async () => {vi.advanceTimersByTime(3500)})
  expect(screen.getByLabelText('Import.md: processing')).toBeInTheDocument()
  expect(screen.getByText('Guide.pdf').closest('tr')).toBe(documentRow)
  expect(screen.getByText('Import.md').closest('tr')).toBe(jobRow)
  expect(screen.queryByText('Refreshing documents…')).not.toBeInTheDocument()
})

it('gives deletion priority over a slow poll so the click is not lost or undone', async () => {
  vi.useFakeTimers()
  await act(async () => {render(<DocumentsPanel {...props}/>)})
  let finish!: (value:DocumentLibrary) => void
  vi.mocked(api.library).mockReturnValueOnce(new Promise(resolve => {finish=resolve}))
    .mockResolvedValue({...listing,items:[],total:0})
  act(() => vi.advanceTimersByTime(3500))
  const signal = vi.mocked(api.library).mock.calls[1][2]!
  await act(async () => {fireEvent.click(screen.getByLabelText('Delete Guide.pdf'))})
  expect(signal.aborted).toBe(true)
  expect(api.remove).toHaveBeenCalledWith('key',11)
  expect(screen.queryByText('Guide.pdf')).not.toBeInTheDocument()
  await act(async () => finish(listing))
  expect(screen.queryByText('Guide.pdf')).not.toBeInTheDocument()
  expect(screen.getByText('Removed Guide.pdf.')).toBeInTheDocument()
})

it('keeps manual refresh feedback visible without inserting a new status row', async () => {
  render(<DocumentsPanel {...props}/>)
  await screen.findByText('Guide.pdf')
  const status = screen.getByText('Documents update automatically.')
  let finish!: (value:DocumentLibrary) => void
  vi.mocked(api.library).mockReturnValueOnce(new Promise(resolve => {finish=resolve}))
  fireEvent.click(screen.getByRole('button',{name:'Refresh documents'}))
  expect(screen.getByText('Refreshing documents…')).toBe(status)
  expect(screen.getByRole('button',{name:'Refresh documents'})).toBeDisabled()
  fireEvent.click(screen.getByRole('button',{name:'Refresh documents'}))
  expect(api.library).toHaveBeenCalledTimes(2)
  expect(screen.getByText('Guide.pdf')).toBeInTheDocument()
  await act(async () => finish(listing))
  expect(screen.getByText('Documents update automatically.')).toBe(status)
})

it('pauses polling in hidden/offline tabs and refreshes quietly on return', async () => {
  vi.useFakeTimers()
  await act(async () => {render(<DocumentsPanel {...props}/>)})
  const visibility = vi.spyOn(document,'visibilityState','get').mockReturnValue('hidden')
  await act(async () => {vi.advanceTimersByTime(7000)})
  expect(api.library).toHaveBeenCalledTimes(1)
  visibility.mockReturnValue('visible')
  await act(async () => {document.dispatchEvent(new Event('visibilitychange'))})
  expect(api.library).toHaveBeenCalledTimes(2)
  const online = vi.spyOn(navigator,'onLine','get').mockReturnValue(false)
  await act(async () => {vi.advanceTimersByTime(7000)})
  expect(api.library).toHaveBeenCalledTimes(2)
  online.mockReturnValue(true)
  await act(async () => {window.dispatchEvent(new Event('online'))})
  expect(api.library).toHaveBeenCalledTimes(3)
  expect(screen.queryByText('Refreshing documents…')).not.toBeInTheDocument()
})

it('cancels polling and listeners on unmount', async () => {
  vi.useFakeTimers()
  let unmount!: () => void
  await act(async () => {({unmount} = render(<DocumentsPanel {...props}/>))})
  vi.mocked(api.library).mockReturnValueOnce(new Promise(() => {}))
  act(() => vi.advanceTimersByTime(3500))
  const signal = vi.mocked(api.library).mock.calls[1][2]!
  unmount()
  expect(signal.aborted).toBe(true)
  act(() => {
    vi.advanceTimersByTime(7000)
    document.dispatchEvent(new Event('visibilitychange'))
    window.dispatchEvent(new Event('online'))
  })
  expect(api.library).toHaveBeenCalledTimes(2)
})

it('ignores older filter results and clears protected content for 403', async () => {
  let finish!: (value:DocumentLibrary) => void
  vi.mocked(api.library).mockReturnValueOnce(new Promise(resolve => {finish=resolve}))
  render(<DocumentsPanel {...props}/>)
  fireEvent.change(screen.getByLabelText('Filter documents'),{target:{value:'new'}})
  await screen.findByText('Guide.pdf')
  await act(async () => finish({...listing,items:[{...row,title:'Obsolete.pdf'}]}))
  expect(screen.queryByText('Obsolete.pdf')).not.toBeInTheDocument()
  vi.mocked(api.library).mockRejectedValueOnce(new ApiError(403,'Denied'))
  fireEvent.click(screen.getByRole('button',{name:'Refresh documents'}))
  await screen.findByRole('alert')
  expect(screen.queryByText('Guide.pdf')).not.toBeInTheDocument()
})

it('removes a failed upload with its own confirmation and disables running uploads', async () => {
  vi.mocked(api.library).mockResolvedValue({...listing,items:[
    {...row,kind:'upload',id:'failed-id',title:'Failed.txt',status:'failed',assigned_users:null},
    {...row,kind:'upload',id:'queued-id',title:'Queued.txt',status:'queued',assigned_users:null},
    {...row,kind:'upload',id:'processing-id',title:'Processing.txt',status:'processing',assigned_users:null},
  ]})
  render(<DocumentsPanel {...props}/>)
  expect(await screen.findByLabelText('Remove failed upload Queued.txt')).toBeDisabled()
  expect(screen.getByLabelText('Remove failed upload Processing.txt')).toBeDisabled()
  fireEvent.click(screen.getByLabelText('Remove failed upload Failed.txt'))
  await waitFor(() => expect(api.removeJob).toHaveBeenCalledWith('key','failed-id'))
  expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('Remove failed upload'))
  expect(api.remove).not.toHaveBeenCalled()
})

it('adjusts to the server-clamped page after document deletion', async () => {
  window.history.replaceState({}, '', '/documents?page=2')
  vi.mocked(api.library).mockResolvedValueOnce({...listing,page:2,total:21,pages:2})
  render(<DocumentsPanel {...props}/>)
  fireEvent.click(await screen.findByLabelText('Delete Guide.pdf'))
  await waitFor(() => expect(new URLSearchParams(window.location.search).get('page')).toBe('1'))
  expect(api.remove).toHaveBeenCalledWith('key',11)
  expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('indexed chunks'))
})

it('honors cancellation, keeps content on cleanup failure and permits retry', async () => {
  vi.mocked(api.library).mockResolvedValue({...listing,items:[{...row,kind:'upload',id:'failed',status:'failed'}]})
  vi.spyOn(window,'confirm').mockReturnValueOnce(false).mockReturnValue(true)
  vi.mocked(api.removeJob).mockRejectedValueOnce(new ApiError(503,'Job retained'))
  render(<DocumentsPanel {...props}/>)
  const remove = await screen.findByLabelText('Remove failed upload Guide.pdf')
  fireEvent.click(remove)
  expect(api.removeJob).not.toHaveBeenCalled()
  fireEvent.click(remove)
  await screen.findByText(/Job retained/)
  expect(screen.getByText('Guide.pdf')).toBeInTheDocument()
  fireEvent.click(screen.getByLabelText('Remove failed upload Guide.pdf'))
  await waitFor(() => expect(api.removeJob).toHaveBeenCalledTimes(2))
})

it('preserves upload, PDF, reindex and neutral access controls', async () => {
  render(<DocumentsPanel {...props}/>)
  await screen.findByText('Guide.pdf')
  expect(screen.getByLabelText('View PDF Guide.pdf')).toBeInTheDocument()
  const file = new File(['synthetic'],'Guide.pdf',{type:'application/pdf'})
  fireEvent.change(screen.getByLabelText('Reindex Guide.pdf'),{target:{files:[file]}})
  await waitFor(() => expect(api.reindex).toHaveBeenCalledWith('key',11,file))
  await screen.findByText('Reindexed Guide.pdf.')
  fireEvent.change(screen.getByLabelText('Select documents to upload'),{target:{files:[file]}})
  await waitFor(() => expect(api.uploadQueued).toHaveBeenCalledWith('key',file))
  await screen.findByText('Queued for indexing')
  vi.mocked(api.library).mockResolvedValue({...listing,items:[{...row,can_manage:false,assigned_users:null}]})
  fireEvent.click(screen.getByRole('button',{name:'Refresh documents'}))
  await screen.findByText('Authorized access')
  expect(screen.queryByLabelText('Manage access for Guide.pdf')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Delete Guide.pdf')).not.toBeInTheDocument()
})
