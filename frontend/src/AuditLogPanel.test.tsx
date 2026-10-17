import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import AuditLogPanel from './AuditLogPanel'
import {api,ApiError} from './api'
import type {AuditLog} from './types'

vi.mock('./api',async original => {
  const actual=await original<typeof import('./api')>()
  return {...actual,api:{...actual.api,adminAuditLog:vi.fn()}}
})
const log:AuditLog={items:[{id:1,created_at:'2026-10-17T00:00:00Z',user_id:2,username:'editor',action:'search',document_id:11,document_title:'Policy.pdf',result_count:0}],
  total:21,page:1,page_size:20,pages:2,actions:['search','document.create'],users:[{id:2,username:'editor'}]}
const props={apiKey:'key',onUnauthorized:vi.fn()}
beforeEach(() => {
  window.history.replaceState({},'','/audit-log')
  vi.clearAllMocks();vi.mocked(api.adminAuditLog).mockReset().mockResolvedValue(log)
})
afterEach(cleanup)

it('shows recorded metadata including zero results and unavailable documents',async () => {
  vi.mocked(api.adminAuditLog).mockResolvedValue({...log,items:[log.items[0],{...log.items[0],id:2,document_id:12,document_title:null,result_count:null}]})
  render(<AuditLogPanel {...props}/>)
  await screen.findByText('Policy.pdf (#11)')
  expect(screen.getByText('Deleted or unavailable document (#12)')).toBeInTheDocument()
  expect(screen.getByRole('cell',{name:'0'})).toBeInTheDocument()
  expect(screen.getAllByRole('columnheader').map(cell => cell.textContent)).toEqual(['Date (UTC)','User','Action','Document','Results'])
})

it('restores deep-linked filters and applies/reset filters with pagination in the URL',async () => {
  window.history.replaceState({},'','/audit-log?page=2&page_size=50&action=search&user_id=2&date_from=2026-10-16&date_to=2026-10-17')
  vi.mocked(api.adminAuditLog).mockImplementation(async (_,query) => ({...log,page:Number(query.get('page')),page_size:Number(query.get('page_size')),total:101,pages:3}))
  render(<AuditLogPanel {...props}/>)
  await screen.findByText('Policy.pdf (#11)')
  expect(screen.getByLabelText('Audit action')).toHaveValue('search')
  expect(screen.getByLabelText('Audit user')).toHaveValue('2')
  expect(screen.getByLabelText('Audit start date')).toHaveValue('2026-10-16')
  fireEvent.change(screen.getByLabelText('Audit action'),{target:{value:'document.create'}})
  expect(api.adminAuditLog).toHaveBeenCalledOnce()
  fireEvent.click(screen.getByRole('button',{name:'Apply filters'}))
  await waitFor(() => expect(api.adminAuditLog).toHaveBeenCalledTimes(2))
  expect(new URLSearchParams(window.location.search).get('page')).toBe('1')
  expect(new URLSearchParams(window.location.search).get('action')).toBe('document.create')
  await screen.findByText('Policy.pdf (#11)')
  fireEvent.change(screen.getByLabelText('Rows per page'),{target:{value:'100'}})
  await waitFor(() => expect(api.adminAuditLog).toHaveBeenCalledTimes(3))
  fireEvent.click(screen.getByRole('button',{name:'Reset filters'}))
  await waitFor(() => expect(screen.getByLabelText('Audit action')).toHaveValue(''))
  expect(new URLSearchParams(window.location.search).has('date_from')).toBe(false)
})

it('retains data after refresh failures and retries with duplicate-click protection',async () => {
  render(<AuditLogPanel {...props}/>)
  await screen.findByText('Policy.pdf (#11)')
  let fail!:(error:Error)=>void
  vi.mocked(api.adminAuditLog).mockReturnValueOnce(new Promise((_,reject) => {fail=reject}))
  const refresh=screen.getByRole('button',{name:'Refresh audit log'})
  fireEvent.click(refresh);fireEvent.click(refresh)
  expect(api.adminAuditLog).toHaveBeenCalledTimes(2)
  await act(async () => fail(new Error('Temporary failure')))
  expect(screen.getByRole('alert')).toHaveTextContent('Previously loaded events may be out of date')
  expect(screen.getByText('Policy.pdf (#11)')).toBeInTheDocument()
  fireEvent.click(refresh)
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
})

it.each([401,403])('clears events on HTTP %i',async status => {
  render(<AuditLogPanel {...props}/>)
  await screen.findByText('Policy.pdf (#11)')
  vi.mocked(api.adminAuditLog).mockRejectedValueOnce(new ApiError(status,'Denied'))
  fireEvent.click(screen.getByRole('button',{name:'Refresh audit log'}))
  await screen.findByRole('alert')
  expect(screen.queryByText('Policy.pdf (#11)')).not.toBeInTheDocument()
  expect(screen.queryByRole('option',{name:'editor'})).not.toBeInTheDocument()
  expect(props.onUnauthorized).toHaveBeenCalledTimes(status===401 ? 1 : 0)
})

it('clamps empty result pages and ignores a late previous-session result',async () => {
  window.history.replaceState({},'','/audit-log?page=99')
  let finish!:(value:AuditLog)=>void
  vi.mocked(api.adminAuditLog).mockReturnValueOnce(new Promise(resolve => {finish=resolve}))
    .mockResolvedValue({...log,items:[],total:0,page:1,pages:1})
  const view=render(<AuditLogPanel {...props}/>)
  view.rerender(<AuditLogPanel {...props} apiKey="new-session"/>)
  await screen.findByText('No audit events match these filters.')
  await waitFor(() => expect(new URLSearchParams(window.location.search).get('page')).toBe('1'))
  await act(async () => finish(log))
  expect(screen.queryByText('Policy.pdf (#11)')).not.toBeInTheDocument()
})
