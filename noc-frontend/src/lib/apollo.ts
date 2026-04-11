import { ApolloClient, InMemoryCache, HttpLink, split } from '@apollo/client'
import { GraphQLWsLink } from '@apollo/client/link/subscriptions'
import { getMainDefinition } from '@apollo/client/utilities'
import { createClient } from 'graphql-ws'

const GQL_HTTP = import.meta.env.VITE_GRAPHQL_URL || 'http://localhost:8888/graphql'
const GQL_WS  = import.meta.env.VITE_GRAPHQL_WS_URL || 'ws://localhost:8888/graphql-ws'

const httpLink = new HttpLink({ uri: GQL_HTTP })

const wsLink = new GraphQLWsLink(createClient({ url: GQL_WS }))

const splitLink = split(
  ({ query }) => {
    const def = getMainDefinition(query)
    return def.kind === 'OperationDefinition' && def.operation === 'subscription'
  },
  wsLink,
  httpLink,
)

export const apolloClient = new ApolloClient({
  link: splitLink,
  cache: new InMemoryCache(),
  defaultOptions: { watchQuery: { fetchPolicy: 'cache-and-network' } },
})
