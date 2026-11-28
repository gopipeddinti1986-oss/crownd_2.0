// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {AccountProfile} from './AccountProfile';
import type {User} from '../services/api';

const getMock=vi.hoisted(()=>vi.fn());const putMock=vi.hoisted(()=>vi.fn());
vi.mock('../services/api',async()=>({api:{get:getMock,put:putMock}}));
const creator={id:4,name:'Creator One',email:'creator@example.com',role:'creator' as const};
function mount(user:User=creator){const client=new QueryClient({defaultOptions:{queries:{retry:false}}});const onUpdate=vi.fn();const notify=vi.fn();return {onUpdate,notify,...render(<QueryClientProvider client={client}><AccountProfile user={user} onUpdate={onUpdate} notify={notify}/></QueryClientProvider>)};}

describe('account profile integration',()=>{
 afterEach(()=>cleanup());
 beforeEach(()=>{getMock.mockReset();putMock.mockReset();getMock.mockResolvedValue({data:{...creator,email_verified:true,profile:{username:'creator_one',niche:'Food',location:'India',bio:'Old bio',platform:'Instagram',followers:500,engagement:2.5,availability:true,verification:'unverified'}}});putMock.mockResolvedValue({data:{...creator,name:'Creator Updated',profile:{bio:'Updated bio'}}});});
 it('loads and saves creator profile values through the account API',async()=>{const {onUpdate,notify}=mount();expect(await screen.findByDisplayValue('Old bio')).toBeTruthy();fireEvent.change(screen.getByLabelText('Bio'),{target:{value:'Updated bio'}});fireEvent.change(screen.getByLabelText('Followers',{exact:false}),{target:{value:'1200'}});fireEvent.click(screen.getByRole('button',{name:'Save profile'}));await waitFor(()=>expect(putMock).toHaveBeenCalledWith('/me/profile',expect.objectContaining({bio:'Updated bio',followers:1200})));expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({name:'Creator Updated'}));expect(notify).toHaveBeenCalledWith('Profile updated.');});
 it('limits brand settings to brand profile fields and reports save errors',async()=>{getMock.mockResolvedValueOnce({data:{id:8,name:'Brand',email:'brand@example.com',role:'brand',profile:{name:'Brand',industry:'Retail',website:'https://brand.example',description:'Brand bio',verification:'unverified'}}});putMock.mockRejectedValueOnce({response:{data:{detail:'Website must be HTTPS'}}});const brand={id:8,name:'Brand',email:'brand@example.com',role:'brand' as const};const {notify}=mount(brand);expect(await screen.findByDisplayValue('Retail')).toBeTruthy();fireEvent.change(screen.getByLabelText('Industry'),{target:{value:'Wellness'}});fireEvent.click(screen.getByRole('button',{name:'Save profile'}));await waitFor(()=>expect(putMock).toHaveBeenCalledWith('/me/profile',expect.objectContaining({industry:'Wellness'})));await waitFor(()=>expect(notify).toHaveBeenCalledWith('Website must be HTTPS'));});
});
