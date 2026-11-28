// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {ApplicationsPage} from './App';
import type {User} from './services/api';
const getMock=vi.hoisted(()=>vi.fn());const patchMock=vi.hoisted(()=>vi.fn());const postMock=vi.hoisted(()=>vi.fn());
vi.mock('./services/api',async importOriginal=>{const original=await importOriginal<typeof import('./services/api')>();return {...original,api:{get:getMock,patch:patchMock,post:postMock}};});
const application={id:21,campaign_id:3,campaign:'Spring partnership',creator_id:5,creator:'Creator One',message:'I am interested',status:'pending',created_at:'2026-01-01T00:00:00Z'};
const creator:User={id:5,name:'Creator One',email:'creator@example.com',role:'creator'};const brand:User={id:3,name:'Brand One',email:'brand@example.com',role:'brand'};
function mount(user:User){const client=new QueryClient({defaultOptions:{queries:{retry:false}}});const notify=vi.fn();return {notify,...render(<QueryClientProvider client={client}><ApplicationsPage user={user} notify={notify}/></QueryClientProvider>)};}
describe('application review UI access and persistence',()=>{beforeEach(()=>{getMock.mockReset();patchMock.mockReset();postMock.mockReset();getMock.mockResolvedValue({data:[application]});patchMock.mockResolvedValue({data:{id:21,status:'accepted'}});postMock.mockResolvedValue({data:{id:21,status:'withdrawn'}})});afterEach(()=>cleanup());
 it('lets creators see their status but not brand-only review actions',async()=>{mount(creator);expect(await screen.findByText('pending')).toBeTruthy();expect(screen.queryByRole('button',{name:/Accept application/})).toBeNull();expect(screen.getByRole('button',{name:'Withdraw application 21'})).toBeTruthy();});
 it('lets a creator withdraw a pending application and refreshes the persisted status',async()=>{getMock.mockReset();getMock.mockResolvedValueOnce({data:[application]}).mockResolvedValue({data:[{...application,status:'withdrawn'}]});const {notify}=mount(creator);fireEvent.click(await screen.findByRole('button',{name:'Withdraw application 21'}));await waitFor(()=>expect(postMock).toHaveBeenCalledWith('/applications/21/withdraw'));expect(notify).toHaveBeenCalledWith('Application withdrawn.');expect(await screen.findByText('withdrawn')).toBeTruthy();expect(screen.queryByRole('button',{name:'Withdraw application 21'})).toBeNull();});
 it('lets a brand review and refreshes its application list',async()=>{const {notify}=mount(brand);fireEvent.click(await screen.findByRole('button',{name:'Accept application 21'}));await waitFor(()=>expect(patchMock).toHaveBeenCalledWith('/applications/21',{status:'accepted'}));expect(notify).toHaveBeenCalledWith('Application accepted.');});
 it('shows a retry action for a failed applications request',async()=>{getMock.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({data:[]});mount(creator);expect(await screen.findByRole('alert')).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'Retry'}));expect(await screen.findByText('Your submitted applications will appear here.')).toBeTruthy();});
});
