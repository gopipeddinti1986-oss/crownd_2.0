// @vitest-environment jsdom
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import type {ReactNode} from 'react';
import {AdminOperations} from './AdminOperations';

const apiMock=vi.hoisted(()=>({get:vi.fn(),post:vi.fn()}));
vi.mock('../services/api',()=>({api:apiMock}));
const notify=vi.fn();
function mount(node:ReactNode){const client=new QueryClient({defaultOptions:{queries:{retry:false}}});return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);}
beforeEach(()=>{vi.clearAllMocks();apiMock.get.mockImplementation(async(path:string)=>{
 if(path==='/admin/operations')return {data:{service:{api_liveness:'available',database_query:'available'},integrations:{email_delivery:'not_probed'},queues:{active_users:3,open_risk_flags:1,open_disputes:0,unverified_creators:1,unverified_brands:0,campaigns_needing_moderation:2},notifications:{delivery:'sql_outbox_available',provider:'disabled_or_incomplete',worker_status:'not_measured',pending:0}}};
 if(path==='/admin/users')return {data:{items:[{id:9,name:'Test Creator',email_masked:'t***@example.test',role:'creator',active:true,email_verified:true,verification:'unverified'}],total:1}};
 if(path==='/admin/campaigns')return {data:{items:[],total:0}};
 if(path==='/admin/disputes')return {data:{items:[],total:0}};
 if(path==='/admin/audit-events')return {data:{items:[],total:0}};
 return {data:{}};
 });apiMock.post.mockResolvedValue({data:{ok:true}});});
afterEach(()=>cleanup());

describe('Phase 7 platform administration UI',()=>{
 it('labels the API/database probe and notification worker status accurately',async()=>{
  mount(<AdminOperations notify={notify}/>);
  expect(await screen.findByText('Administration')).toBeTruthy();
  expect(screen.getByText('API liveness')).toBeTruthy();
  await screen.findAllByText('available');
  expect(screen.getByText('sql_outbox_available')).toBeTruthy();
  expect(screen.getByText(/worker: not_measured/)).toBeTruthy();
  expect(screen.getByText('email delivery')).toBeTruthy();
  expect(screen.getByText('not_probed')).toBeTruthy();
 });
 it('requires a reason and typed confirmation before a suspension request',async()=>{
  const user=userEvent.setup();mount(<AdminOperations notify={notify}/>);
  await user.click(await screen.findByRole('button',{name:'Users & access'}));
  await user.click(await screen.findByRole('button',{name:'Suspend'}));
  const reason=screen.getByPlaceholderText(/Explain the administrative decision/);
  await user.type(reason,'Temporary access restriction for manual review');
  const confirmation=screen.getByLabelText('Type confirmation phrase');
  await user.type(confirmation,'SUSPEND');
  await user.click(screen.getByRole('button',{name:'Confirm action'}));
  await waitFor(()=>expect(apiMock.post).toHaveBeenCalledWith('/admin/users/9/lifecycle',{
   active:false,reason:'Temporary access restriction for manual review',confirmation:'SUSPEND'
  }));
 });
 it('shows unverified profiles as a manual review task',async()=>{
  const user=userEvent.setup();mount(<AdminOperations notify={notify}/>);
  await user.click(await screen.findByRole('button',{name:'Verification'}));
  expect(await screen.findByText('Mark manually verified')).toBeTruthy();
  expect(screen.getByText('MANUAL REVIEW')).toBeTruthy();
 });
});
