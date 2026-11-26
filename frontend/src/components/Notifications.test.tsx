// @vitest-environment jsdom
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter} from 'react-router-dom';
import type {ReactNode} from 'react';
import {AdminDeliveryMonitor,NotificationCenter,NotificationSettings} from './Notifications';

const mock=vi.hoisted(()=>({getNotifications:vi.fn(),markNotificationRead:vi.fn(),markAllNotificationsRead:vi.fn(),getNotificationPreferences:vi.fn(),saveNotificationPreferences:vi.fn(),getAdminDeliverySummary:vi.fn(),getAdminDeliveries:vi.fn()}));
vi.mock('../services/api',()=>mock);
const notify=vi.fn();
function mount(node:ReactNode){const client=new QueryClient({defaultOptions:{queries:{retry:false}}});return render(<QueryClientProvider client={client}><MemoryRouter>{node}</MemoryRouter></QueryClientProvider>);}
beforeEach(()=>{
 vi.clearAllMocks();
 mock.getNotifications.mockResolvedValue({items:[{id:5,category:'order',title:'Order updated',body:'<img src=x onerror=alert(1)> status recorded',action_path:'/orders/CR-1',read_at:null,created_at:'2026-01-01T00:00:00Z'}],total:1,unread_count:1,page:1,page_size:20,pages:1});
 mock.markNotificationRead.mockResolvedValue({id:5,read_at:'2026-01-01T00:01:00Z'});mock.markAllNotificationsRead.mockResolvedValue({updated:1});
 mock.getNotificationPreferences.mockResolvedValue({in_app_enabled:true,email_enabled:true,category_settings:{},updated_at:null});
 mock.saveNotificationPreferences.mockImplementation(async(value:any)=>({...value,updated_at:'2026-01-01T00:00:00Z'}));
 mock.getAdminDeliverySummary.mockResolvedValue({counts:{pending:1,sending:0,sent:2,suppressed:1,failed:0},provider:'disabled_or_incomplete',worker_status:'not_measured',latest_queued_at:null,delivery_semantics:'At least once'});
 mock.getAdminDeliveries.mockResolvedValue({items:[{id:3,category:'security',status:'suppressed',attempt_count:1,next_attempt_at:null,last_error_code:'provider_disabled',created_at:'2026-01-01T00:00:00Z',delivered_at:null}],total:1,page:1,page_size:25,pages:1});
});
afterEach(()=>cleanup());

describe('Phase 8 notifications UI',()=>{
 it('renders untrusted notification copy as text and marks only the selected notice read',async()=>{
  const user=userEvent.setup();mount(<NotificationCenter notify={notify}/>);
  expect(await screen.findByText('Order updated')).toBeTruthy();
  expect(screen.getByText('<img src=x onerror=alert(1)> status recorded')).toBeTruthy();
  expect(document.querySelector('img')).toBeNull();
  await user.click(screen.getByRole('button',{name:'Mark read'}));
  await waitFor(()=>expect(mock.markNotificationRead).toHaveBeenCalledWith(5));
 });
 it('saves notification category preferences without altering other channel defaults',async()=>{
  const user=userEvent.setup();mount(<NotificationSettings notify={notify}/>);
  const email=await screen.findByRole('checkbox',{name:'Order email'});
  expect((email as HTMLInputElement).checked).toBe(true);
  await user.click(email);
  await user.click(screen.getByRole('button',{name:/Save settings/}));
  await waitFor(()=>expect(mock.saveNotificationPreferences).toHaveBeenCalled());
  const saved=mock.saveNotificationPreferences.mock.calls[mock.saveNotificationPreferences.mock.calls.length-1]?.[0];
  expect(saved.category_settings.order.email).toBe(false);
  expect(saved.category_settings.order.in_app).toBe(true);
 });
 it('shows delivery state and redacted admin telemetry only',async()=>{
  mount(<AdminDeliveryMonitor notify={notify}/>);
  expect(await screen.findByText('Delivery #3')).toBeTruthy();
  expect(screen.getByText('Provider disabled')).toBeTruthy();
  expect(screen.queryByText(/recipient_id|encrypted_message|@example\./i)).toBeNull();
  expect(screen.getByText(/Worker status:/)).toBeTruthy();
 });
});
