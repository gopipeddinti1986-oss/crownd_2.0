// @vitest-environment jsdom
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter,Route,Routes} from 'react-router-dom';
import type {ReactNode} from 'react';
import {CartPage,CheckoutPage,OrderDetailPage,OrdersPage,ProductDetailPage,ShopPage} from './CustomerCommerce';
import type {CommerceOrder,CommerceProduct,CartData,User} from '../services/api';

const mocks=vi.hoisted(()=>({discoverProducts:vi.fn(),getProduct:vi.fn(),getCart:vi.fn(),addCartItem:vi.fn(),updateCartItem:vi.fn(),removeCartItem:vi.fn(),clearCart:vi.fn(),checkoutOrder:vi.fn(),getOrders:vi.fn(),getOrder:vi.fn(),cancelOrder:vi.fn(),apiGet:vi.fn()}));
vi.mock('../services/api',async importOriginal=>{
  const original=await importOriginal<typeof import('../services/api')>();
  return {...original,discoverProducts:mocks.discoverProducts,getProduct:mocks.getProduct,getCart:mocks.getCart,addCartItem:mocks.addCartItem,updateCartItem:mocks.updateCartItem,removeCartItem:mocks.removeCartItem,clearCart:mocks.clearCart,checkoutOrder:mocks.checkoutOrder,getOrders:mocks.getOrders,getOrder:mocks.getOrder,cancelOrder:mocks.cancelOrder,api:{get:mocks.apiGet}};
});
const user:User={id:7,name:'Casey Customer',email:'casey@example.com',role:'customer'};
const product:CommerceProduct={id:11,name:'Cedar Serum',slug:'cedar-serum',description:'A daily botanical serum.',category:'Beauty',price:'100.00',sale_price:'80.00',effective_price:'80.00',discount_percent:20,stock:5,available:true,status:'active',image_url:'',image_urls:[],specifications:{size:'30 ml'},brand:{id:2,name:'Noya Botanics',website:''},creator_program:null,attribution:null,related_products:[]};
const cart:CartData={items:[{id:31,product,quantity:1,unit_price:'80.00',line_total:'80.00',available:true}],item_count:1,subtotal:'80.00',shipping:'0.00',total:'80.00',currency:'INR',unavailable_count:0,attribution:null};
const order:CommerceOrder={id:'CR-ORDER123456',order_id:'CR-ORDER123456',amount:'80.00',currency:'INR',payment_status:'pending',status:'pending',created_at:'2026-11-25T00:00:00Z',updated_at:'2026-11-25T00:00:00Z',items:[{product_id:11,name:'Cedar Serum',brand:'Noya Botanics',image_url:'',unit_price:'80.00',quantity:1,line_total:'80.00'}],referral:null,customer:{name:user.name,email:user.email},shipping_address:null};
function mountAt(node:ReactNode,path:string){const queryClient=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});return render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={[path]}><Routes><Route path="/shop" element={node}/><Route path="/products/:id" element={node}/><Route path="/cart" element={node}/><Route path="/checkout" element={node}/><Route path="/orders" element={node}/><Route path="/orders/:id" element={node}/></Routes></MemoryRouter></QueryClientProvider>);}
const notify=vi.fn();
beforeEach(()=>{vi.clearAllMocks();mocks.apiGet.mockImplementation((url:string)=>Promise.resolve({data:url.endsWith('categories')?['Beauty']:url.endsWith('brands')?[{id:2,name:'Noya Botanics'}]:[]}));mocks.discoverProducts.mockResolvedValue({items:[product],total:1,page:1,page_size:12,pages:1});mocks.getProduct.mockResolvedValue(product);mocks.getCart.mockResolvedValue(cart);mocks.addCartItem.mockResolvedValue(cart);mocks.updateCartItem.mockResolvedValue(cart);mocks.removeCartItem.mockResolvedValue(undefined);mocks.clearCart.mockResolvedValue(undefined);mocks.checkoutOrder.mockResolvedValue(order);mocks.getOrders.mockResolvedValue({items:[order],total:1,page:1,pages:1});mocks.getOrder.mockResolvedValue(order);mocks.cancelOrder.mockResolvedValue({...order,status:'cancelled'});});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});

describe('customer commerce experience',()=>{
  it('queries product discovery with backend search and renders live products',async()=>{
    const ui=userEvent.setup();mountAt(<ShopPage user={user} notify={notify}/ >,'/shop');
    expect((await screen.findAllByRole('link',{name:/Cedar Serum/i})).length).toBeGreaterThan(0);
    await ui.type(screen.getByRole('searchbox',{name:/Search products/}),'serum');
    await waitFor(()=>expect(mocks.discoverProducts).toHaveBeenLastCalledWith(expect.objectContaining({q:'serum'})));
    await ui.click(screen.getByRole('checkbox',{name:'In stock only'}));
    await waitFor(()=>expect(mocks.discoverProducts).toHaveBeenLastCalledWith(expect.objectContaining({q:'serum',in_stock:true})));
    expect(screen.getByText('Noya Botanics')).toBeTruthy();
  });
  it('shows the filter empty state and lets shoppers clear filters',async()=>{
    mocks.discoverProducts.mockResolvedValue({items:[],total:0,page:1,page_size:12,pages:0});
    const ui=userEvent.setup();mountAt(<ShopPage user={user} notify={notify}/ >,'/shop');
    expect(await screen.findByText('No products match those filters')).toBeTruthy();
    await ui.click(screen.getByRole('button',{name:'Clear all filters'}));
    expect(mocks.discoverProducts).toHaveBeenCalled();
  });
  it('loads product detail and adds selected quantities to the persistent cart',async()=>{
    const ui=userEvent.setup();mountAt(<ProductDetailPage user={user} notify={notify}/ >,'/products/11');
    expect(await screen.findByRole('heading',{name:'Cedar Serum'})).toBeTruthy();
    await ui.click(screen.getByRole('button',{name:'Increase quantity'}));
    await ui.click(screen.getByRole('button',{name:/Add to cart/i}));
    await waitFor(()=>expect(mocks.addCartItem).toHaveBeenCalledWith(11,2));
    expect(notify).toHaveBeenCalledWith('2 × Cedar Serum added to your cart.');
  });
  it('updates and removes a cart line through the API',async()=>{
    const ui=userEvent.setup();mountAt(<CartPage user={user} notify={notify}/ >,'/cart');
    expect(await screen.findByRole('heading',{name:/Good choices/})).toBeTruthy();
    await ui.click(screen.getByRole('button',{name:'Increase Cedar Serum quantity'}));
    await waitFor(()=>expect(mocks.updateCartItem).toHaveBeenCalledWith(31,2));
    await ui.click(screen.getByRole('button',{name:/Remove/}));
    await waitFor(()=>expect(mocks.removeCartItem).toHaveBeenCalledWith(31));
  });
  it('validates checkout fields and posts a server-backed order with an idempotency key',async()=>{
    const ui=userEvent.setup();mountAt(<CheckoutPage user={user} notify={notify}/ >,'/checkout');
    await screen.findByRole('heading',{name:/Where should we send it/});
    const fields=[['Recipient name','Casey Customer'],['Phone number','+91 98765 43210'],['Address line 1','12 Market Road'],['City','Rajamahendravaram'],['State / region','Andhra Pradesh'],['Postal code','533101'],['Country code','IN']];
    for(const [label,value] of fields){const field=screen.getByLabelText(new RegExp(label));await ui.clear(field);await ui.type(field,value);}
    await ui.click(screen.getByRole('button',{name:/Place order/}));
    await waitFor(()=>expect(mocks.checkoutOrder).toHaveBeenCalledWith(expect.objectContaining({name:'Casey Customer',postal_code:'533101'}),expect.any(String)));
  });
  it('shows order history and order progress; cancellation is available for unpaid pending orders',async()=>{
    vi.stubGlobal('confirm',()=>true);
    const ui=userEvent.setup();mountAt(<OrdersPage user={user}/ >,'/orders');
    expect(await screen.findByRole('link',{name:/CR-ORDER123456/})).toBeTruthy();
    cleanup();mountAt(<OrderDetailPage user={user} notify={notify}/ >,'/orders/CR-ORDER123456');
    expect(await screen.findByText('Order progress')).toBeTruthy();
    await ui.click(screen.getByRole('button',{name:'Cancel order'}));
    await waitFor(()=>expect(mocks.cancelOrder).toHaveBeenCalledWith('CR-ORDER123456'));
  });
  it('renders a recoverable error state instead of fake data',async()=>{
    mocks.discoverProducts.mockRejectedValue(new Error('offline'));
    mountAt(<ShopPage user={user} notify={notify}/ >,'/shop');
    expect(await screen.findByText('We couldn’t load that just now')).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:'Try again'}));
  });
});
