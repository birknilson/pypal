# -*- coding: utf-8 -*-

import logging

from pypal import currency
from pypal.util import check_required, set_nonempty_param

PRODUCTION_ENDPOINT = 'https://svcs.paypal.com'
SANDBOX_ENDPOINT = 'https://svcs.sandbox.paypal.com'

ACTION_PAY = 'PAY'
ACTION_CREATE = 'CREATE'
ACTION_PAY_PRIMARY = 'PAY_PRIMARY'

SUPPORTED_PAY_ACTIONS = frozenset([ACTION_PAY,
                                   ACTION_CREATE,
                                   ACTION_PAY_PRIMARY])


FEE_PAYER_SENDER = 'SENDER'
FEE_PAYER_PRIMARY_RECEIVER = 'PRIMARYRECEIVER'
FEE_PAYER_EACH_RECEIVER = 'EACHRECEIVER'
FEE_PAYER_SECONDARY_RECEIVERS = 'SECONDARYONLY'

SUPPORTED_FEE_PAYERS = frozenset([FEE_PAYER_SENDER,
                                  FEE_PAYER_PRIMARY_RECEIVER,
                                  FEE_PAYER_EACH_RECEIVER,
                                  FEE_PAYER_SECONDARY_RECEIVERS])

EXECUTE_STATUS_CREATED = 'CREATED'
EXECUTE_STATUS_COMPLETED = 'COMPLETED'
EXECUTE_STATUS_INCOMPLETE = 'INCOMPLETE'
EXECUTE_STATUS_ERROR = 'ERROR'
EXECUTE_STATUS_REVERSAL_ERROR = 'REVERSALERROR'
EXECUTE_STATUS_PROCESSING = 'PROCESSING'
EXECUTE_STATUS_PENDING = 'PENDING'

##############################################################################
# FUNCTIONS WHICH FURTHER AIDS IMPLEMENTATION OF THIS SERVICE
##############################################################################

class ReceiverList(list):
    """An extension of the native list type which ensures all contained items
    are dictionaries - containing the necessary arguments needed per receiver.

    """
    def __init__(self, iterable):
        if iterable:
            self.extend(iterable)

    def append(self, obj):
        email = obj.get('email', None)
        amount = obj.get('amount', None)
        if not email and not amount:
            return False

        sanitized = {'email': obj.get('email'),
                     'amount': obj.get('amount'),
                     'primary': obj.get('primary', 'false')}
        super(type(self), self).append(sanitized)

    def extend(self, iterable):
        for obj in iterable:
            self.append(obj)

def call(client, method, params):
    """A wrapper of the ``'pypal.Client.call'`` method which
    will set the API endpoints for this service depending
    on the environment, i.e sandbox or not.

    :param client: An instance of ``'pypal.Client'``
    :param method: The API method to execute
    :param params: The arguments to send
    """
    endpoint = (PRODUCTION_ENDPOINT, SANDBOX_ENDPOINT)
    endpoint = endpoint[int(client.config.in_sandbox)]
    return client.call('AdaptivePayments', method,
                       endpoint=endpoint, **params)

def get_payment_url(client,
                    action_type,
                    currency_code,
                    cancel_url,
                    return_url,
                    ipn_callback_url=None,
                    receivers=None,
                    fees_payer=None,
                    extra={},
                    embedded=False):
    """Executes the Pay API call and returns the intended redirect URL
    directly using the necessary pay key returned in the PayPal response.

    This function is a wrapper of ``'pay'`` which will execute the necessary
    API calls and using the response this function will generate the URL.
    """
    response = pay(**locals())
    if not response.success:
        return None

    pay_key = response.get('payKey', None)
    if not pay_key:
        return None
    return generate_pay_url(client, pay_key, embedded=embedded)

def generate_pay_url(client, pay_key, embedded=False):
    """Retrieves the pay key associated with prepared payment procedures and
    generates the intended URL to redirect end-users in order to finialize
    payments.

    :param client: An instance of ``'pypal.Client'``
    :param pay_key: The payment token received from PayPal
    :param embedded: Whether or not to generate an url which
                     is intended for an embedded payment experience.
    """
    paths = ('/cgi-bin/webscr?cmd=_ap-payment&paykey=%s',
             '/webapps/adaptivepayment/flow/pay?paykey=%s')
    return client.get_paypal_url(paths[embedded] % pay_key)

##############################################################################
# FUNCTIONS WHICH DIRECTLY CORRESPONDS TO PAYPAL API CALLS
##############################################################################

def pay(client,
        action_type,
        currency_code,
        cancel_url,
        return_url,
        ipn_callback_url,
        receivers=None,
        fees_payer=None,
        extra={}):
    """Execute the Pay API call which will prepare the payment procedure.
    Most importantly it will return a pay key which should be utilized in
    order to identify the transaction.

    :param client: An instance of ``'pypal.Client'``
    :param action_type: The payment action type
    :param currency_code: Which currency code to utilize in the transaction
    :param cancel_url: The URL which the end-user is sent to on
                       payment cancellation.
    :param return_url: The URL which the end-user is sent to on completed
                       payment, in all cases be it success or failure.
    :param ipn_callback_url: The URL which will receive the IPN notifications
                             related to this operation. The Adaptive Payment API
                             requires this to be explicitly set and does not
                             fallback on the default IPN URL for the
                             application.
    :param receivers: A list of the receivers of this transaction
    :param fees_payer: Who will pay the PayPal fees
    :param extra: Additional key-value arguments to send to PayPal
    """
    check_required(locals(), ('cancel_url', 'return_url', 'currency_code',
                              'action_type', 'receivers', 'ipn_callback_url'))

    if not currency.is_valid_code(currency_code):
        raise ValueError('Given currency code (%s) '
                         'is not supported' % currency_code)

    if action_type not in SUPPORTED_PAY_ACTIONS:
        raise ValueError('Given payment action (%s) is not any of the '
                         'supported types; %s' % (action_type,
                                                  SUPPORTED_PAY_ACTIONS))

    if fees_payer and fees_payer not in SUPPORTED_FEE_PAYERS:
        raise ValueError('Given value (%s) for the fees_payer argument '
                         'is not supported by PayPal' % fees_payer)

    if not isinstance(receivers, ReceiverList):
        if not isinstance(receivers, (list, tuple)):
            receivers = [receivers]
        receivers = ReceiverList(receivers)

    extra.update({'actionType': action_type,
                  'receiverList': { 'receiver': receivers },
                  'currencyCode': currency_code,
                  'cancelUrl': cancel_url,
                  'returnUrl': return_url})

    set_nonempty_param(extra, 'ipnNotificationUrl', ipn_callback_url)
    set_nonempty_param(extra, 'feesPayer', fees_payer)
    return call(client, 'Pay', extra)

def get_payment_options(client, pay_key):
    return call(client, 'GetPaymentOptions', {'payKey': pay_key})

def set_payment_options(client,
                        pay_key,
                        receiver_options,
                        display_options=None,
                        sender_options=None,
                        shipping_address_id=None,
                        initiating_entity=None,
                        extra={}):
    """Execute the SetPaymentOptions API call which will customize
    behavior of the payment procedure at PayPal.

    :param client: An instance of ``'pypal.Client'``
    :param pay_key: The PayPal token associated with the transaction
    :param sender_options: Dictionary containing sender customizations
    :param receiver_options: Dictionary containing receiver customizations
    :param display_options: Dictionary containing display customizations
    :param shipping_address_id: The PayPal identifier for the shipping
                                address to set.
    :param initiating_entity: Dictionary containing initiating entity
                              customizations.
    :param extra: Additional key-value arguments to send to PayPal
    """
    extra['payKey'] = pay_key
    set_nonempty_param(extra, 'initiatingEntity', initiating_entity)
    set_nonempty_param(extra, 'displayOptions', display_options)
    set_nonempty_param(extra, 'shippingAddressId', shipping_address_id)
    set_nonempty_param(extra, 'senderOptions', sender_options)
    set_nonempty_param(extra, 'receiverOptions', receiver_options)
    return call(client, 'SetPaymentOptions', extra)

def execute(client, pay_key):
    return call(client, 'ExecutePayment', {'payKey': pay_key})

def get_shipping_addresses(client, key):
    """Execute the GetShippingAddresses API call which will retrieve
    the shipping address which was set by the buyer.

    :param token: Either a payment or preapproval key
    """
    return call(client, 'GetShippingAddresses', {'key': key})
