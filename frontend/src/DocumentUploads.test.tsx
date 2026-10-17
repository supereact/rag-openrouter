import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach,beforeEach,expect,it,vi } from 'vitest'
import DocumentUploads from './DocumentUploads'
import {api,ApiError} from './api'

vi.mock('./api',async original => {
  const actual = await original<typeof import('./api')>()
  return {...actual,api:{...actual.api,uploadQueued:vi.fn()}}
})
const props = {apiKey:'key',disabled:false,onUnauthorized:vi.fn(),onQueued:vi.fn()}
const response = {id:'11111111-1111-4111-8111-111111111111',filename:'test.md',status:'queued' as const,created_at:'2026-10-17T00:00:00Z'}
const files = ['One.pdf','Two.md','Three.txt'].map(name => new File(['synthetic'],name))
beforeEach(() => {vi.clearAllMocks();vi.mocked(api.uploadQueued).mockReset().mockResolvedValue(response)})
afterEach(cleanup)
function select(items:File[]) {fireEvent.change(screen.getByLabelText('Select documents to upload'),{target:{files:items}})}

it('uploads multiple selected files sequentially and reports each accepted file',async () => {
  let finish!: (value:typeof response) => void
  vi.mocked(api.uploadQueued).mockReturnValueOnce(new Promise(resolve => {finish=resolve}))
  render(<DocumentUploads {...props}/>)
  expect(screen.getByLabelText('Select documents to upload')).toHaveAttribute('multiple')
  select(files)
  expect(api.uploadQueued).toHaveBeenCalledTimes(1)
  expect(screen.getByLabelText('Select documents to upload')).toBeDisabled()
  expect(screen.getByText('Uploading…')).toBeInTheDocument()
  expect(screen.getAllByText('Waiting')).toHaveLength(2)
  await act(async () => finish(response))
  await screen.findByText('3 queued · 0 failed · 0 invalid · 0 remaining')
  expect(vi.mocked(api.uploadQueued).mock.calls.map(call => call[1])).toEqual(files)
  expect(props.onQueued).toHaveBeenCalledTimes(3)
  expect(screen.getAllByText('Queued for indexing')).toHaveLength(3)
  expect(screen.getByLabelText('Select documents to upload')).toBeEnabled()
})

it('validates each file independently and still uploads valid files',async () => {
  const huge = new File(['synthetic'],'Huge.pdf')
  Object.defineProperty(huge,'size',{value:50*1024*1024+1})
  render(<DocumentUploads {...props}/>)
  select([files[0],new File(['x'],'Unsupported.exe'),new File([],'Empty.txt'),huge,files[1]])
  await screen.findByText('2 queued · 0 failed · 3 invalid · 0 remaining')
  expect(api.uploadQueued).toHaveBeenCalledTimes(2)
  expect(screen.getByText('Maximum file size is 50 MB.')).toBeInTheDocument()
  expect(screen.getByText('The file is empty.')).toBeInTheDocument()
})

it('continues after individual failure and retries only failed files',async () => {
  vi.mocked(api.uploadQueued).mockRejectedValueOnce(new ApiError(503,'Queue unavailable'))
  render(<DocumentUploads {...props}/>)
  select(files)
  await screen.findByText('2 queued · 1 failed · 0 invalid · 0 remaining')
  fireEvent.click(screen.getByRole('button',{name:'Retry failed uploads'}))
  await screen.findByText('3 queued · 0 failed · 0 invalid · 0 remaining')
  expect(api.uploadQueued).toHaveBeenCalledTimes(4)
  expect(vi.mocked(api.uploadQueued).mock.calls[3][1]).toBe(files[0])
  expect(props.onQueued).toHaveBeenCalledTimes(3)
})

it.each([401,403])('stops remaining uploads when authorization fails with %i',async status => {
  vi.mocked(api.uploadQueued).mockRejectedValueOnce(new ApiError(status,'Denied'))
  render(<DocumentUploads {...props}/>)
  select(files)
  await screen.findByText('0 queued · 3 failed · 0 invalid · 0 remaining')
  expect(api.uploadQueued).toHaveBeenCalledTimes(1)
  expect(props.onUnauthorized).toHaveBeenCalledTimes(status===401 ? 1 : 0)
  expect(props.onQueued).not.toHaveBeenCalled()
})

it('reports ambiguous network failures without silently replaying uploads',async () => {
  vi.mocked(api.uploadQueued).mockRejectedValueOnce(new ApiError(0,'Connection lost'))
  render(<DocumentUploads {...props}/>)
  select([files[0]])
  await screen.findByText(/Check the library before retrying/)
  expect(api.uploadQueued).toHaveBeenCalledOnce()
})

it('stops issuing uploads after navigation/unmount and ignores late completion',async () => {
  let finish!: (value:typeof response) => void
  vi.mocked(api.uploadQueued).mockReturnValueOnce(new Promise(resolve => {finish=resolve}))
  const view=render(<DocumentUploads {...props}/>)
  select(files)
  view.unmount()
  await act(async () => finish(response))
  expect(api.uploadQueued).toHaveBeenCalledOnce()
  expect(props.onQueued).not.toHaveBeenCalled()
})

it('resets files on session changes and ignores a stale unauthorized response',async () => {
  let fail!: (value:unknown) => void
  vi.mocked(api.uploadQueued).mockReturnValueOnce(new Promise((_,reject) => {fail=reject}))
  const view=render(<DocumentUploads {...props}/>)
  select(files)
  view.rerender(<DocumentUploads {...props} apiKey="new-key"/>)
  expect(screen.queryByText('One.pdf')).not.toBeInTheDocument()
  await act(async () => fail(new ApiError(401,'Old session')))
  expect(props.onUnauthorized).not.toHaveBeenCalled()
  expect(api.uploadQueued).toHaveBeenCalledOnce()
})

it('handles further selections and clearing the local upload list without deleting jobs',async () => {
  render(<DocumentUploads {...props}/>)
  select([files[0]])
  await screen.findByText('1 queued · 0 failed · 0 invalid · 0 remaining')
  select([files[1]])
  await screen.findByText('2 queued · 0 failed · 0 invalid · 0 remaining')
  expect(within(screen.getByLabelText('Selected uploads')).getAllByRole('listitem')).toHaveLength(2)
  fireEvent.click(screen.getByRole('button',{name:'Clear upload list'}))
  expect(screen.queryByLabelText('Selected uploads')).not.toBeInTheDocument()
  expect(api.uploadQueued).toHaveBeenCalledTimes(2)
})

it('guards disabled selection and repeated input events during an upload',async () => {
  const view=render(<DocumentUploads {...props} disabled/>)
  select(files)
  expect(api.uploadQueued).not.toHaveBeenCalled()
  view.rerender(<DocumentUploads {...props}/>)
  let finish!: (value:typeof response) => void
  vi.mocked(api.uploadQueued).mockReturnValueOnce(new Promise(resolve => {finish=resolve}))
  select([files[0]])
  select([files[1]])
  expect(api.uploadQueued).toHaveBeenCalledOnce()
  await act(async () => finish(response))
  await waitFor(() => expect(screen.getByLabelText('Select documents to upload')).toBeEnabled())
  expect(api.uploadQueued).toHaveBeenCalledOnce()
})
